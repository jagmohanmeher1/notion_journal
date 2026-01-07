"""
Automated Daily Journal to Notion
Tracks daily Cursor activity and GitHub commits, creates/updates Notion journal entries
"""
import os
import sys
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv
from notion_client import Client
from github import Github

# Load environment variables
# Get the directory where this script is located
script_dir = Path(__file__).parent
env_path = script_dir / '.env'
load_dotenv(dotenv_path=env_path)

class GitRepositoryScanner:
    """Scans for git repositories and gets today's commits"""
    
    def __init__(self, project_paths: List[str]):
        self.project_paths = project_paths
        self.today = datetime.now().date()
    
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
    
    def get_today_commits(self, repo_path: Path) -> List[Dict]:
        """Get commits made today from a git repository"""
        commits = []
        try:
            # Get commits from today
            since = self.today.strftime("%Y-%m-%d 00:00:00")
            until = (datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
            
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
                    commit_date = parts[3]
                    commit_message = parts[4] if len(parts) > 4 else ""
                    commit_body = parts[5] if len(parts) > 5 else ""
                    
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
                        'date': commit_date,
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
    
    def scan_all_repos(self) -> List[Dict]:
        """Scan all repositories and get today's commits"""
        all_commits = []
        repos = self.find_git_repos()
        
        print(f"Found {len(repos)} git repositories")
        
        for repo in repos:
            commits = self.get_today_commits(repo)
            if commits:
                print(f"  {repo.name}: {len(commits)} commits today")
                all_commits.extend(commits)
        
        return all_commits


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
        self._title_property = None
        self._date_property = None
        self._get_database_schema()
    
    def _get_database_schema(self):
        """Get database schema to find property names"""
        try:
            database = self.notion.databases.retrieve(database_id=self.database_id)
            properties = database.get("properties", {})
            
            # Find title property (usually the first property or one named "Name", "Title", etc.)
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get("type")
                if prop_type == "title":
                    self._title_property = prop_name
                    break
            
            # Find date property
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get("type")
                if prop_type == "date":
                    self._date_property = prop_name
                    break
            
            # Fallback: use first property as title if no title found
            if not self._title_property and properties:
                self._title_property = list(properties.keys())[0]
            
            if not self._date_property:
                # Try common date property names
                for name in ["Date", "date", "Date Created", "Created"]:
                    if name in properties and properties[name].get("type") == "date":
                        self._date_property = name
                        break
        except Exception as e:
            print(f"Warning: Could not get database schema: {e}")
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
    
    def create_journal_entry(self, local_commits: List[Dict], github_commits: List[Dict]) -> Dict:
        """Create a new journal entry with today's activity"""
        today = datetime.now()
        date_str = today.strftime("%Y-%m-%d")
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
        
        # Summary section
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "📊 Daily Summary"}}]
            }
        })
        
        total_commits = len(local_commits) + len(github_commits)
        repos_worked = len(repos_dict) + len(set(c['repo'] for c in github_commits))
        
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
                    commit_text = f"{commit['hash']}: {commit['message']}"
                    children.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": commit_text},
                                    "annotations": {"link": commit.get('url', '')}
                                }
                            ]
                        }
                    })
        
        # Notes section
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "📝 Notes"}}]
            }
        })
        
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "Add your notes and reflections here..."}}]
            }
        })
        
        # Create the page
        try:
            # Build properties based on schema
            properties = {}
            
            # Add title property
            if self._title_property:
                properties[self._title_property] = {
                    "title": [{"text": {"content": title}}]
                }
            
            # Add date property
            if self._date_property:
                properties[self._date_property] = {
                    "date": {"start": date_str}
                }
            
            new_page = self.notion.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=children
            )
            return new_page
        except Exception as e:
            print(f"Error creating journal entry: {e}")
            print(f"Title property: {self._title_property}, Date property: {self._date_property}")
            raise
    
    def update_journal_entry(self, page_id: str, local_commits: List[Dict], github_commits: List[Dict]):
        """Update existing journal entry with new commits"""
        # For now, we'll append new commits to the existing page
        # In a more sophisticated version, we could merge and deduplicate
        
        # Get existing page content
        try:
            existing_blocks = self.notion.blocks.children.list(block_id=page_id)
            
            # Append new commits section if there are new commits
            new_children = []
            
            if local_commits or github_commits:
                new_children.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": "🔄 Additional Activity"}}]
                    }
                })
                
                # Add new commits (similar to create_journal_entry)
                # For simplicity, we'll just note that there's additional activity
                new_children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": f"Found {len(local_commits) + len(github_commits)} additional commits"}}]
                    }
                })
            
            if new_children:
                self.notion.blocks.children.append(block_id=page_id, children=new_children)
        except Exception as e:
            print(f"Error updating journal entry: {e}")


def main():
    """Main function"""
    print("=" * 60)
    print("Automated Daily Journal - Starting...")
    print("=" * 60)
    
    # Load configuration
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    
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
    scanner = GitRepositoryScanner(project_paths)
    local_commits = scanner.scan_all_repos()
    print(f"   Found {len(local_commits)} local commits today")
    
    github_commits = []
    if github_token and github_username:
        print("\n2. Fetching GitHub commits...")
        try:
            github_tracker = GitHubCommitTracker(github_token, github_username)
            github_commits = github_tracker.get_today_commits()
            print(f"   Found {len(github_commits)} GitHub commits today")
        except Exception as e:
            print(f"   Warning: Could not fetch GitHub commits: {e}")
    else:
        print("\n2. Skipping GitHub (token/username not configured)")
    
    # Create or update journal entry
    print("\n3. Creating/updating Notion journal entry...")
    journal = NotionJournal(notion_token, database_id)
    
    existing_entry = journal.find_today_entry()
    
    if existing_entry:
        print("   Found existing entry for today, updating...")
        journal.update_journal_entry(existing_entry['id'], local_commits, github_commits)
        print(f"   [OK] Updated journal entry: {existing_entry.get('url', 'N/A')}")
    else:
        print("   Creating new entry for today...")
        new_entry = journal.create_journal_entry(local_commits, github_commits)
        print(f"   [OK] Created journal entry: {new_entry.get('url', 'N/A')}")
    
    print("\n" + "=" * 60)
    print("Journal update complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
