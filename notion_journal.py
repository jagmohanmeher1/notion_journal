"""
Automated Daily Journal to Notion
Tracks daily Cursor activity and GitHub commits, creates/updates Notion journal entries
With AI-generated summaries and date-based organization
"""
import os
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict
from dotenv import load_dotenv
from notion_client import Client
from github import Github
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Load environment variables
# Get the directory where this script is located
script_dir = Path(__file__).parent
env_path = script_dir / '.env'
load_dotenv(dotenv_path=env_path)

class GitRepositoryScanner:
    """Scans for git repositories and gets commits by date"""
    
    def __init__(self, project_paths: List[str], days_back: int = 7):
        self.project_paths = project_paths
        self.today = datetime.now().date()
        self.days_back = days_back
    
    def is_git_repo(self, path: Path) -> bool:
        """Check if a directory is a git repository"""
        return (path / '.git').exists()
    
    def find_git_repos(self) -> List[Path]:
        """Find all git repositories in project paths"""
        repos = []
        for project_path in self.project_paths:
            path = Path(project_path)
            if not path.exists():
                continue
            
            # Check if the path itself is a git repo
            if self.is_git_repo(path):
                repos.append(path)
            
            # Recursively search for git repos (limit depth to avoid too deep)
            try:
                for item in path.rglob('.git'):
                    try:
                        repo_path = item.parent
                        if repo_path not in repos:
                            repos.append(repo_path)
                    except (OSError, PermissionError):
                        # Skip inaccessible paths
                        continue
            except (PermissionError, OSError) as e:
                # Only print warning if it's a significant error
                if "cannot find the path" not in str(e).lower():
                    print(f"Warning: Could not scan {path}: {e}")
        
        return repos
    
    def get_commits_by_date_range(self, repo_path: Path, start_date: datetime.date, end_date: datetime.date) -> List[Dict]:
        """Get commits from a date range from a git repository"""
        commits = []
        try:
            # Get commits from date range
            since = start_date.strftime("%Y-%m-%d 00:00:00")
            until = end_date.strftime("%Y-%m-%d 23:59:59")
            
            # Run git log command
            result = subprocess.run(
                ['git', 'log', 
                 '--since', since,
                 '--until', until,
                 '--pretty=format:%H|%an|%ae|%ad|%s|%b',
                 '--date=iso'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return commits
            
            # Parse commits
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                
                parts = line.split('|', 5)
                if len(parts) >= 5:
                    commit_hash = parts[0]
                    author_name = parts[1]
                    author_email = parts[2]
                    commit_date_str = parts[3]
                    commit_message = parts[4] if len(parts) > 4 else ""
                    commit_body = parts[5] if len(parts) > 5 else ""
                    
                    # Parse commit date to get the date part
                    try:
                        # Handle ISO format dates (e.g., "2024-01-15 10:30:45 +0000")
                        date_part = commit_date_str.split(' ')[0]  # Get "2024-01-15"
                        commit_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                    except:
                        try:
                            # Try ISO format parsing
                            commit_datetime = datetime.fromisoformat(commit_date_str.replace(' ', 'T').split('+')[0].split('-')[0])
                            commit_date = commit_datetime.date()
                        except:
                            # Fallback: use today's date
                            commit_date = self.today
                    
                    # Get files changed
                    files_result = subprocess.run(
                        ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', commit_hash],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    files_changed = files_result.stdout.strip().split('\n') if files_result.returncode == 0 else []
                    files_changed = [f for f in files_changed if f]
                    
                    commits.append({
                        'hash': commit_hash[:7],
                        'author': author_name,
                        'email': author_email,
                        'date': commit_date_str,
                        'date_obj': commit_date,
                        'message': commit_message,
                        'body': commit_body,
                        'files': files_changed,
                        'repo': repo_path.name,
                        'repo_path': str(repo_path)
                    })
        except subprocess.TimeoutExpired:
            print(f"Warning: Timeout getting commits from {repo_path}")
        except Exception as e:
            print(f"Error getting commits from {repo_path}: {e}")
        
        return commits
    
    def scan_all_repos_by_date(self) -> Dict[datetime.date, List[Dict]]:
        """Scan all repositories and get commits grouped by date"""
        all_commits_by_date = defaultdict(list)
        repos = self.find_git_repos()
        
        print(f"Found {len(repos)} git repositories")
        
        # Get date range
        end_date = self.today
        start_date = end_date - timedelta(days=self.days_back)
        
        print(f"Scanning commits from {start_date} to {end_date}")
        
        for repo in repos:
            commits = self.get_commits_by_date_range(repo, start_date, end_date)
            if commits:
                print(f"  {repo.name}: {len(commits)} commits found")
                for commit in commits:
                    commit_date = commit.get('date_obj', self.today)
                    all_commits_by_date[commit_date].append(commit)
        
        return dict(all_commits_by_date)


class AIReportGenerator:
    """Generates AI-powered summaries and reports of daily work using local Ollama or OpenAI"""
    
    def __init__(self, ollama_model: Optional[str] = None, openai_key: Optional[str] = None, silent: bool = False):
        # Store these for mood generation
        self.ollama_model = ollama_model or os.getenv("OLLAMA_MODEL", "llama3.2")
        self.openai_key = openai_key or os.getenv("OPENAI_API_KEY")
        self.use_ollama = os.getenv("USE_OLLAMA", "true").lower() == "true"
        self.ollama_available = False
        self.openai_client = None
        self.silent = silent  # Don't print messages if True
        
        # Try to initialize Ollama (preferred, free, local)
        if self.use_ollama and OLLAMA_AVAILABLE:
            try:
                # Test if Ollama is running
                ollama.list()
                self.ollama_available = True
                if not self.silent:
                    print(f"   [OK] Ollama initialized with model: {self.ollama_model}")
            except Exception as e:
                if not self.silent:
                    print(f"   [WARN] Ollama not available: {e}")
                    print(f"   [INFO] Install Ollama from https://ollama.com and run: ollama pull {self.ollama_model}")
                self.ollama_available = False
        
        # Fallback to OpenAI if Ollama not available and OpenAI key provided
        if not self.ollama_available and self.openai_key and OPENAI_AVAILABLE:
            try:
                self.openai_client = OpenAI(api_key=self.openai_key)
                if not self.silent:
                    print(f"   [OK] OpenAI initialized as fallback")
            except Exception as e:
                if not self.silent:
                    print(f"   [WARN] Could not initialize OpenAI client: {e}")
    
    def generate_daily_report(self, date: datetime.date, commits: List[Dict], github_commits: List[Dict]) -> str:
        """Generate an AI-powered daily work report"""
        # Prepare commit information for AI
        commit_summary = self._prepare_commit_summary(commits, github_commits)
        
        prompt = f"""You are a technical journal assistant. Analyze the following work activity for {date.strftime('%B %d, %Y')} and write a comprehensive daily work report.

The report should:
1. Provide a high-level summary of what was accomplished
2. Identify the main projects and areas of focus
3. Highlight key technical work, features, or improvements
4. Note any patterns or themes in the work
5. Be written in a professional but conversational tone
6. Be 2-3 paragraphs long

Work Activity:
{commit_summary}

Write a comprehensive daily work report:"""

        # Try Ollama first (free, local)
        if self.ollama_available:
            try:
                response = ollama.chat(
                    model=self.ollama_model,
                    messages=[
                        {"role": "system", "content": "You are a helpful technical writing assistant that creates insightful daily work reports."},
                        {"role": "user", "content": prompt}
                    ],
                    options={
                        "temperature": 0.7,
                        "num_predict": 500
                    }
                )
                return response['message']['content'].strip()
            except Exception as e:
                print(f"   [WARN] Ollama generation failed: {e}, trying fallback...")
        
        # Fallback to OpenAI if available
        if self.openai_client:
            try:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful technical writing assistant that creates insightful daily work reports."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=500
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"   [WARN] OpenAI generation failed: {e}")
        
        # Final fallback to basic summary
        return self._generate_basic_summary(date, commits, github_commits)
    
    def _prepare_commit_summary(self, commits: List[Dict], github_commits: List[Dict]) -> str:
        """Prepare a summary of commits for AI analysis"""
        summary_parts = []
        
        # Group by repository
        repos = defaultdict(list)
        for commit in commits + github_commits:
            repo_name = commit.get('repo', 'Unknown')
            repos[repo_name].append(commit)
        
        for repo_name, repo_commits in repos.items():
            summary_parts.append(f"\nRepository: {repo_name}")
            summary_parts.append(f"Commits: {len(repo_commits)}")
            for commit in repo_commits[:10]:  # Limit to 10 commits per repo
                msg = commit.get('message', '')
                files_count = len(commit.get('files', []))
                summary_parts.append(f"  - {msg} ({files_count} files changed)")
        
        return "\n".join(summary_parts)
    
    def _generate_basic_summary(self, date: datetime.date, commits: List[Dict], github_commits: List[Dict]) -> str:
        """Generate a basic summary without AI"""
        total_commits = len(commits) + len(github_commits)
        repos = set(c.get('repo', 'Unknown') for c in commits + github_commits)
        
        summary = f"On {date.strftime('%B %d, %Y')}, I worked on {len(repos)} project(s) with a total of {total_commits} commits. "
        
        if repos:
            summary += f"Main projects included: {', '.join(list(repos)[:3])}. "
        
        summary += "The work involved various improvements and feature development across these repositories."
        
        return summary
    
    def generate_mood(self, date: datetime.date, commits: List[Dict], github_commits: List[Dict]) -> str:
        """Generate a mood based on the work done"""
        if not self.ollama_available and not self.openai_client:
            # Fallback: simple mood based on commit count
            total_commits = len(commits) + len(github_commits)
            if total_commits == 0:
                return "Neutral"
            elif total_commits < 3:
                return "Focused"
            elif total_commits < 10:
                return "Productive"
            else:
                return "Very Productive"
        
        # Use AI to generate mood
        commit_summary = self._prepare_commit_summary(commits, github_commits)
        
        prompt = f"""Based on the following work activity for {date.strftime('%B %d, %Y')}, determine the mood/feeling of the work day.

Work Activity:
{commit_summary}

Respond with ONLY a single word mood from this list: Productive, Focused, Challenging, Creative, Busy, Relaxed, Energetic, Satisfied, Frustrated, Excited, Neutral, Accomplished, Overwhelmed, Motivated, Tired, Inspired, Determined, Calm, Stressed, Happy

Choose the ONE word that best describes the mood of this work day:"""

        try:
            if self.ollama_available:
                response = ollama.chat(
                    model=self.ollama_model,
                    messages=[
                        {"role": "system", "content": "You are a mood analyzer. Respond with only a single word."},
                        {"role": "user", "content": prompt}
                    ],
                    options={
                        "temperature": 0.3,
                        "num_predict": 20
                    }
                )
                mood = response['message']['content'].strip().split()[0].capitalize()
            elif self.openai_client:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a mood analyzer. Respond with only a single word."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=10
                )
                mood = response.choices[0].message.content.strip().split()[0].capitalize()
            else:
                mood = "Productive"
            
            # Validate mood is from the list
            valid_moods = ["Productive", "Focused", "Challenging", "Creative", "Busy", "Relaxed", 
                          "Energetic", "Satisfied", "Frustrated", "Excited", "Neutral", "Accomplished", 
                          "Overwhelmed", "Motivated", "Tired", "Inspired", "Determined", "Calm", 
                          "Stressed", "Happy"]
            
            # Check if mood matches any valid mood (case-insensitive)
            for valid in valid_moods:
                if valid.lower() == mood.lower():
                    return valid
            
            return "Productive"  # Default fallback
        except Exception as e:
            print(f"   [WARN] Mood generation failed: {e}")
            # Fallback based on commit count
            total_commits = len(commits) + len(github_commits)
            if total_commits == 0:
                return "Neutral"
            elif total_commits < 3:
                return "Focused"
            else:
                return "Productive"


class GitHubCommitTracker:
    """Fetches today's commits from GitHub"""
    
    def __init__(self, token: str, username: str):
        from github import Auth
        auth = Auth.Token(token)
        self.github = Github(auth=auth)
        self.user = self.github.get_user(username)
        self.today = datetime.now().date()
    
    def get_today_commits(self) -> List[Dict]:
        """Get all commits made today across all repositories"""
        commits = []
        
        try:
            # Get all repositories (including private if token has access)
            repos = self.user.get_repos()
            
            for repo in repos:
                try:
                    # Get commits from today
                    since = datetime.combine(self.today, datetime.min.time()).replace(tzinfo=timezone.utc)
                    until = datetime.now(timezone.utc)
                    
                    repo_commits = repo.get_commits(since=since, author=self.user.login)
                    
                    for commit in repo_commits:
                        commit_date = commit.commit.author.date.date()
                        if commit_date == self.today:
                            commits.append({
                                'hash': commit.sha[:7],
                                'message': commit.commit.message.split('\n')[0],
                                'repo': repo.name,
                                'repo_url': repo.html_url,
                                'date': commit.commit.author.date.isoformat(),
                                'url': commit.html_url
                            })
                except Exception as e:
                    print(f"Warning: Could not get commits from {repo.name}: {e}")
                    continue
        except Exception as e:
            print(f"Error fetching GitHub commits: {e}")
        
        return commits


class NotionJournal:
    """Manages journal entries in Notion"""
    
    def __init__(self, token: str, database_id: str):
        self.notion = Client(auth=token)
        self.database_id = database_id
        # Explicit property names (can be overridden via .env if needed)
        # These should match your Notion database column names exactly
        self.title_prop_name = os.getenv("NOTION_TITLE_PROPERTY", "Title")
        self.date_prop_name = os.getenv("NOTION_DATE_PROPERTY", "Date")
        self.mood_prop_name = os.getenv("NOTION_MOOD_PROPERTY", "Mood")
        self.content_prop_name = os.getenv("NOTION_CONTENT_PROPERTY", "Content")

        self._title_property = None
        self._date_property = None
        self._mood_property = None
        self._content_property = None
        self._database_properties = {}
        self._get_database_schema()
    
    def _get_database_schema(self):
        """Get database schema to find property names"""
        try:
            database = self.notion.databases.retrieve(database_id=self.database_id)
            properties = database.get("properties", {})
            self._database_properties = properties
            
            # Debug: Print all properties found
            print(f"\n   [DEBUG] Found {len(properties)} properties in database:")
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get("type")
                print(f"      - {prop_name} ({prop_type})")
            
            # Find title property (usually the first property or one named "Name", "Title", etc.)
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get("type")
                if prop_type == "title":
                    self._title_property = prop_name
                    print(f"   [DEBUG] Found title property: {prop_name}")
                    break
            
            # Find date property - case insensitive search
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get("type")
                if prop_type == "date":
                    # Prefer exact match "Date" over other date properties
                    if prop_name.lower() == "date":
                        self._date_property = prop_name
                        print(f"   [DEBUG] Found date property: {prop_name}")
                        break
            
            # If no exact "Date" match, find any date property
            if not self._date_property:
                for prop_name, prop_info in properties.items():
                    prop_type = prop_info.get("type")
                    if prop_type == "date":
                        self._date_property = prop_name
                        print(f"   [DEBUG] Found date property (fallback): {prop_name}")
                        break
            
            # Find mood property - case insensitive, any type
            for prop_name, prop_info in properties.items():
                if prop_name.lower() == "mood":
                    self._mood_property = prop_name
                    mood_type = prop_info.get("type")
                    print(f"   [DEBUG] Found mood property: {prop_name} (type: {mood_type})")
                    break
            
            # Find content property - case insensitive
            for prop_name, prop_info in properties.items():
                if prop_name.lower() == "content":
                    prop_type = prop_info.get("type")
                    # Accept any text-like type
                    if prop_type in ["rich_text", "text"]:
                        self._content_property = prop_name
                        print(f"   [DEBUG] Found content property: {prop_name} (type: {prop_type})")
                        break
            
            # Fallback: use first property as title if no title found
            if not self._title_property and properties:
                self._title_property = list(properties.keys())[0]
                print(f"   [DEBUG] Using first property as title: {self._title_property}")
            
            if not self._date_property:
                # Try common date property names (case insensitive)
                for prop_name, prop_info in properties.items():
                    if prop_name.lower() in ["date", "date created", "created"] and prop_info.get("type") == "date":
                        self._date_property = prop_name
                        print(f"   [DEBUG] Found date property (by name match): {prop_name}")
                        break
            
            print(f"   [DEBUG] Detected properties - Title: {self._title_property}, Date: {self._date_property}, Mood: {self._mood_property}, Content: {self._content_property}")
            print(f"   [DEBUG] Using explicit names - Title: {self.title_prop_name}, Date: {self.date_prop_name}, Mood: {self.mood_prop_name}, Content: {self.content_prop_name}")
        except Exception as e:
            print(f"Warning: Could not get database schema: {e}")
            import traceback
            traceback.print_exc()
            # Use defaults
            self._title_property = "Name"
            self._date_property = "Date"
    
    def find_today_entry(self) -> Optional[Dict]:
        """Find today's journal entry if it exists"""
        today = datetime.now().date()
        date_str = today.isoformat()
        
        try:
            # Query database for today's entry
            if self._date_property:
                results = self.notion.databases.query(
                    **{
                        "database_id": self.database_id,
                        "filter": {
                            "property": self._date_property,
                            "date": {
                                "equals": date_str
                            }
                        }
                    }
                )
                
                if results.get("results"):
                    return results["results"][0]
        except Exception as e:
            print(f"Error finding today's entry: {e}")
        
        return None
    
    def find_entry_by_date(self, target_date: datetime.date) -> Optional[Dict]:
        """Find journal entry for a specific date"""
        date_str = target_date.isoformat()
        
        try:
            # Simple strategy: search by title "Journal - YYYY-MM-DD" and reuse first match
            expected_title = f"Journal - {date_str}"

            print(f"   [DEBUG] Searching for existing entry with title '{expected_title}'")

            results = self.notion.search(
                query=expected_title,
                filter={"property": "object", "value": "page"},
            )

            pages = results.get("results", [])
            print(f"   [DEBUG] Search returned {len(pages)} pages for '{expected_title}'")

            if pages:
                page = pages[0]
                print(f"   [DEBUG] Reusing first matching page for {date_str}: {page.get('id')}")
                return page
        except Exception as e:
            print(f"Error finding entry for {date_str}: {e}")
        
        return None
    
    def create_journal_entry(self, date: datetime.date, local_commits: List[Dict], github_commits: List[Dict], ai_report: str) -> Dict:
        """Create a new journal entry with activity for a specific date"""
        date_str = date.strftime("%Y-%m-%d")
        title = f"Journal - {date_str}"
        
        # Organize commits by repository
        repos_dict = {}
        for commit in local_commits:
            repo_name = commit['repo']
            if repo_name not in repos_dict:
                repos_dict[repo_name] = []
            repos_dict[repo_name].append(commit)
        
        # Build content blocks
        children = []
        
        # AI-Generated Daily Report (main content)
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "📝 Daily Work Report"}}]
            }
        })
        
        # Split AI report into paragraphs
        report_paragraphs = ai_report.split('\n\n')
        for para in report_paragraphs:
            if para.strip():
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": para.strip()}}]
                    }
                })
        
        # Statistics section
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "📊 Activity Statistics"}}]
            }
        })
        
        total_commits = len(local_commits) + len(github_commits)
        repos_worked = len(repos_dict) + len(set(c.get('repo', 'Unknown') for c in github_commits))
        total_files = sum(len(c.get('files', [])) for c in local_commits + github_commits)
        
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"Total commits: {total_commits}"}}]
            }
        })
        
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"Repositories worked on: {repos_worked}"}}]
            }
        })
        
        if total_files > 0:
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": f"Files changed: {total_files}"}}]
                }
            })
        
        # Local commits section
        if local_commits:
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "💻 Local Commits"}}]
                }
            })
            
            for repo_name, commits in repos_dict.items():
                children.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": f"📁 {repo_name}"}}]
                    }
                })
                
                for commit in commits:
                    commit_text = f"{commit['hash']}: {commit['message']}"
                    if commit['files']:
                        commit_text += f" ({len(commit['files'])} files)"
                    
                    children.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": commit_text}}]
                        }
                    })
        
        # GitHub commits section
        if github_commits:
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "🌐 GitHub Commits"}}]
                }
            })
            
            github_repos = {}
            for commit in github_commits:
                repo_name = commit['repo']
                if repo_name not in github_repos:
                    github_repos[repo_name] = []
                github_repos[repo_name].append(commit)
            
            for repo_name, commits in github_repos.items():
                children.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": f"📁 {repo_name}"}}]
                    }
                })
                
                for commit in commits:
                    # Include GitHub URL directly in the text instead of using an invalid 'annotations.link' field
                    commit_text = f"{commit['hash']}: {commit['message']}"
                    url = commit.get('url')
                    if url:
                        commit_text += f" ({url})"
                    
                    children.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": commit_text}
                                }
                            ]
                        }
                    })
        
        # Detailed Commit Log section
        if local_commits or github_commits:
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "💻 Detailed Commit Log"}}]
                }
            })
        
        # Create the page
        try:
            # Build properties based on schema
            properties = {}
            
            # Add title property (use explicit name, fallback to detected)
            title_prop = self.title_prop_name or self._title_property
            if title_prop:
                properties[title_prop] = {
                    "title": [{"text": {"content": title}}]
                }
                print(f"   [DEBUG] Setting title property '{title_prop}' = '{title}'")
            else:
                print(f"   [WARN] Title property not found!")
            
            # Add date property (use explicit name, fallback to detected)
            date_prop = self.date_prop_name or self._date_property
            if date_prop:
                properties[date_prop] = {
                    "date": {"start": date_str}
                }
                print(f"   [DEBUG] Setting date property '{date_prop}' = '{date_str}'")
            else:
                print(f"   [WARN] Date property not found!")
            
            # Add mood property (use explicit name)
            if self.mood_prop_name:
                mood_prop_name = self.mood_prop_name
                mood_prop_info = self._database_properties.get(mood_prop_name, {})
                if not mood_prop_info:
                    print(f"   [WARN] Mood property '{mood_prop_name}' not found in database schema")
                    mood_type = None
                else:
                    mood_type = mood_prop_info.get("type")
                
                print(f"   [DEBUG] Setting mood property '{mood_prop_name}' (type: {mood_type})")
                
                # Generate mood using AI (create generator instance, silent mode)
                ai_gen = AIReportGenerator(ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"), 
                                          openai_key=os.getenv("OPENAI_API_KEY"),
                                          silent=True)
                mood = ai_gen.generate_mood(date, local_commits, github_commits)
                print(f"   [DEBUG] Generated mood: {mood}")
                
                if mood_type == "select":
                    # For select type, try to match mood to available options
                    options = mood_prop_info.get("select", {}).get("options", [])
                    print(f"   [DEBUG] Select options available: {[opt.get('name') for opt in options]}")
                    mood_lower = mood.lower()
                    
                    # Try exact match first
                    matched = False
                    for opt in options:
                        if opt.get("name", "").lower() == mood_lower:
                            properties[mood_prop_name] = {"select": {"name": opt.get("name")}}
                            print(f"   [DEBUG] Matched mood to option: {opt.get('name')}")
                            matched = True
                            break
                    
                    # Try partial match
                    if not matched:
                        for opt in options:
                            if mood_lower in opt.get("name", "").lower() or opt.get("name", "").lower() in mood_lower:
                                properties[mood_prop_name] = {"select": {"name": opt.get("name")}}
                                print(f"   [DEBUG] Partial matched mood to option: {opt.get('name')}")
                                matched = True
                                break
                    
                    # Use first option if no match
                    if not matched and options:
                        properties[mood_prop_name] = {"select": {"name": options[0].get("name")}}
                        print(f"   [DEBUG] Using first option as fallback: {options[0].get('name')}")
                elif mood_type == "rich_text":
                    properties[mood_prop_name] = {
                        "rich_text": [{"text": {"content": mood}}]
                    }
                    print(f"   [DEBUG] Set mood as rich_text: {mood}")
                elif mood_type == "text":
                    properties[mood_prop_name] = {
                        "text": [{"text": {"content": mood}}]
                    }
                    print(f"   [DEBUG] Set mood as text: {mood}")
                else:
                    print(f"   [WARN] Unknown mood property type: {mood_type}")
            else:
                print(f"   [WARN] Mood property name not configured (expected 'Mood')!")
            
            # Add content property (use AI report, explicit name)
            if self.content_prop_name:
                content_prop_name = self.content_prop_name
                content_prop_info = self._database_properties.get(content_prop_name, {})
                if not content_prop_info:
                    print(f"   [WARN] Content property '{content_prop_name}' not found in database schema")
                    content_type = "rich_text"
                else:
                    content_type = content_prop_info.get("type")
                
                print(f"   [DEBUG] Setting content property '{content_prop_name}' (type: {content_type})")
                
                # Use AI report as content (first 2000 chars to avoid limits)
                content_text = ai_report[:2000] if len(ai_report) > 2000 else ai_report
                
                if content_type == "rich_text":
                    # For rich_text, use simple format
                    properties[content_prop_name] = {
                        "rich_text": [{"text": {"content": content_text}}]
                    }
                    print(f"   [DEBUG] Set content as rich_text ({len(content_text)} chars)")
                elif content_type == "text":
                    properties[content_prop_name] = {
                        "text": [{"text": {"content": content_text}}]
                    }
                    print(f"   [DEBUG] Set content as text ({len(content_text)} chars)")
                else:
                    print(f"   [WARN] Unknown content property type: {content_type}, trying rich_text")
                    properties[content_prop_name] = {
                        "rich_text": [{"text": {"content": content_text}}]
                    }
            else:
                print(f"   [WARN] Content property name not configured (expected 'Content')!")
            
            # Debug: Print all properties being set
            print(f"   [DEBUG] Properties to set: {list(properties.keys())}")
            
            # Try to populate other common properties
            try:
                # Try to add commit count if property exists
                for prop_name, prop_info in self._database_properties.items():
                    prop_type = prop_info.get("type")
                    if prop_type == "number" and ("commit" in prop_name.lower() or "count" in prop_name.lower()):
                        properties[prop_name] = {"number": total_commits}
                    elif prop_type == "select" and "status" in prop_name.lower():
                        # Set a default status if available
                        options = prop_info.get("select", {}).get("options", [])
                        if options:
                            properties[prop_name] = {"select": {"name": options[0].get("name", "Active")}}
            except:
                pass  # Ignore errors when trying to populate additional properties
            
            print(f"   [DEBUG] Creating page with {len(properties)} properties")
            new_page = self.notion.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=children
            )
            print(f"   [DEBUG] Page created successfully")
            return new_page
        except Exception as e:
            print(f"Error creating journal entry: {e}")
            print(f"Title property: {self._title_property}, Date property: {self._date_property}")
            print(f"Mood property: {self._mood_property}, Content property: {self._content_property}")
            print(f"Properties dict: {properties}")
            import traceback
            traceback.print_exc()
            raise
    
    def update_journal_entry(self, page_id: str, date: datetime.date, local_commits: List[Dict], github_commits: List[Dict], ai_report: str):
        """Update existing journal entry with new commits and regenerate AI report"""
        # For now, we'll recreate the entry with updated content
        # In a more sophisticated version, we could merge and deduplicate
        
        try:
            # Get existing page
            page = self.notion.pages.retrieve(page_id=page_id)
            
            # Delete all existing blocks and recreate
            try:
                blocks = self.notion.blocks.children.list(block_id=page_id)
                for block in blocks.get("results", []):
                    try:
                        self.notion.blocks.delete(block_id=block["id"])
                    except:
                        pass
            except:
                pass
            
            # Recreate with new content (reuse create_journal_entry logic)
            # For simplicity, we'll just append a note about the update
            new_children = [{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": f"Updated on {datetime.now().strftime('%Y-%m-%d %H:%M')} with {len(local_commits) + len(github_commits)} commits"}}]
                }
            }]
            
            self.notion.blocks.children.append(block_id=page_id, children=new_children)
        except Exception as e:
            print(f"Error updating journal entry: {e}")


def main():
    """Main function"""
    print("=" * 60)
    print("Automated Daily Journal with AI Reports - Starting...")
    print("=" * 60)
    
    # Load configuration
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    openai_key = os.getenv("OPENAI_API_KEY")
    days_back = int(os.getenv("DAYS_BACK", "7"))  # How many days back to process
    
    # Project paths to scan (default to common locations)
    project_paths_str = os.getenv("PROJECT_PATHS", "d:\\projects")
    project_paths = [p.strip() for p in project_paths_str.split(",")]
    
    # Validate required config
    env_file = Path(__file__).parent / '.env'
    if not env_file.exists():
        print(f"Error: .env file not found at {env_file}")
        print("Please create .env file from .env.example and add your credentials")
        sys.exit(1)
    
    if not notion_token:
        print("Error: NOTION_TOKEN not found in .env file")
        print(f"Please check your .env file at {env_file}")
        print("Make sure NOTION_TOKEN is set (without quotes)")
        sys.exit(1)
    
    if not database_id or database_id == "your_database_id_here":
        print("Error: NOTION_DATABASE_ID not found or not configured in .env file")
        print(f"Please check your .env file at {env_file}")
        print("Get your Database ID from your Notion database URL")
        sys.exit(1)
    
    # Initialize components
    print("\n1. Scanning local git repositories...")
    scanner = GitRepositoryScanner(project_paths, days_back=days_back)
    local_commits_by_date = scanner.scan_all_repos_by_date()
    
    total_local_commits = sum(len(commits) for commits in local_commits_by_date.values())
    print(f"   Found {total_local_commits} local commits across {len(local_commits_by_date)} days")
    
    # Get GitHub commits by date
    github_commits_by_date = defaultdict(list)
    if github_token and github_username:
        print("\n2. Fetching GitHub commits...")
        try:
            github_tracker = GitHubCommitTracker(github_token, github_username)
            # Get commits for the date range
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=days_back)
            
            for single_date in (start_date + timedelta(n) for n in range((end_date - start_date).days + 1)):
                since = datetime.combine(single_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                until = datetime.combine(single_date, datetime.max.time()).replace(tzinfo=timezone.utc)
                
                try:
                    repos = github_tracker.user.get_repos()
                    for repo in repos:
                        try:
                            repo_commits = repo.get_commits(since=since, author=github_tracker.user.login)
                            for commit in repo_commits:
                                commit_date = commit.commit.author.date.date()
                                if commit_date == single_date:
                                    github_commits_by_date[commit_date].append({
                                        'hash': commit.sha[:7],
                                        'message': commit.commit.message.split('\n')[0],
                                        'repo': repo.name,
                                        'repo_url': repo.html_url,
                                        'date': commit.commit.author.date.isoformat(),
                                        'url': commit.html_url,
                                        'date_obj': commit_date
                                    })
                        except:
                            continue
                except Exception as e:
                    print(f"   Warning: Error fetching GitHub commits for {single_date}: {e}")
            
            total_github_commits = sum(len(commits) for commits in github_commits_by_date.values())
            print(f"   Found {total_github_commits} GitHub commits across {len(github_commits_by_date)} days")
        except Exception as e:
            print(f"   Warning: Could not fetch GitHub commits: {e}")
    else:
        print("\n2. Skipping GitHub (token/username not configured)")
    
    # Initialize AI report generator
    print("\n3. Initializing AI report generator...")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")
    ai_generator = AIReportGenerator(ollama_model=ollama_model, openai_key=openai_key)
    if ai_generator.ollama_available:
        print(f"   [OK] Using Ollama (local, free) with model: {ollama_model}")
    elif ai_generator.openai_client:
        print("   [OK] Using OpenAI (fallback, requires API key)")
    else:
        print("   [INFO] AI report generation disabled (using basic summaries)")
        print("   [INFO] Install Ollama from https://ollama.com for free AI reports")
    
    # Initialize Notion journal
    journal = NotionJournal(notion_token, database_id)
    
    # Process each date
    print("\n4. Processing journal entries by date...")
    all_dates = set(local_commits_by_date.keys()) | set(github_commits_by_date.keys())
    
    if not all_dates:
        print("   No commits found in the specified date range")
        print("\n" + "=" * 60)
        print("Journal update complete!")
        print("=" * 60)
        return
    
    for date in sorted(all_dates, reverse=True):  # Process most recent first
        local_commits = local_commits_by_date.get(date, [])
        github_commits = github_commits_by_date.get(date, [])
        
        if not local_commits and not github_commits:
            continue
        
        print(f"\n   Processing {date.strftime('%Y-%m-%d')}: {len(local_commits)} local, {len(github_commits)} GitHub commits")
        
        # Generate AI report
        ai_report = ai_generator.generate_daily_report(date, local_commits, github_commits)
        
        # Check if entry exists
        existing_entry = journal.find_entry_by_date(date)
        
        if existing_entry:
            print(f"      Found existing entry, updating...")
            journal.update_journal_entry(existing_entry['id'], date, local_commits, github_commits, ai_report)
            print(f"      [OK] Updated: {existing_entry.get('url', 'N/A')}")
        else:
            print(f"      Creating new entry...")
            new_entry = journal.create_journal_entry(date, local_commits, github_commits, ai_report)
            print(f"      [OK] Created: {new_entry.get('url', 'N/A')}")
    
    print("\n" + "=" * 60)
    print(f"Journal update complete! Processed {len(all_dates)} day(s)")
    print("=" * 60)


if __name__ == "__main__":
    main()
