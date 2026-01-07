# Automated Daily Journal to Notion

Automatically track your daily Cursor activity and GitHub commits, then create/update a journal entry in Notion every day.

## Features

- 🔍 **Scans Local Git Repositories**: Automatically finds and scans all git repositories in your project directories
- 📊 **Tracks Daily Commits**: Collects all commits made today from local repos
- 🌐 **GitHub Integration**: Fetches commits from your GitHub account
- 📝 **Notion Journal**: Creates or updates a daily journal entry in Notion
- ⏰ **Automated**: Runs daily via Windows Task Scheduler or WSL cron

## Setup

### 1. Prerequisites

- Conda installed
- Notion account
- GitHub account (optional, for GitHub commit tracking)
- Git installed

### 2. Create Conda Environment

```bash
cd d:\projects\notion_journal
conda env create -f environment.yml
conda activate notion-journal
```

### 3. Configure Notion

1. Go to https://www.notion.so/my-integrations
2. Create a new integration (you've already created "my_journal")
3. Copy the **Internal Integration Token** (starts with `secret_`)
4. Create a Notion database with these properties:
   - **Name** (Title) - default column
   - **Date** (Date) - for the journal date
5. Copy the **Database ID** from the URL
6. Share the database with your integration:
   - Open database → "..." menu → "Add connections" → Select "my_journal"

### 4. Configure GitHub (Optional)

1. Go to https://github.com/settings/tokens
2. Generate new token (classic)
3. Select scope: `public_repo` (or `repo` for private repos)
4. Copy the token (starts with `ghp_`)

### 5. Configure the Script

1. Copy `.env.example` to `.env`:
   ```bash
   copy .env.example .env
   ```

2. Edit `.env` and fill in your credentials:
   ```env
   NOTION_TOKEN=secret_your_actual_token_here
   NOTION_DATABASE_ID=your_actual_database_id_here
   GITHUB_TOKEN=ghp_your_github_token_here
   GITHUB_USERNAME=your_github_username
   PROJECT_PATHS=d:\projects
   ```

   **Note**: For multiple project paths, separate with commas:
   ```env
   PROJECT_PATHS=d:\projects,c:\dev,/mnt/d/projects
   ```

### 6. Test the Script

```bash
conda activate notion-journal
python notion_journal.py
```

Check your Notion database - you should see a new entry for today!

## Automation

### Windows Task Scheduler

1. Open **Task Scheduler**
2. Click **"Create Basic Task"**
3. Configure:
   - **Name**: `Daily Notion Journal`
   - **Trigger**: Daily at your preferred time (e.g., 9:00 PM)
   - **Action**: Start a program
   - **Program**: Full path to conda's python, e.g.:
     ```
     C:\Users\YourName\anaconda3\envs\notion-journal\python.exe
     ```
   - **Arguments**: `"d:\projects\notion_journal\notion_journal.py"`
   - **Start in**: `d:\projects\notion_journal`
4. Check **"Run whether user is logged on or not"**

### WSL Cron (Alternative)

If you prefer running from WSL:

```bash
# Edit crontab
crontab -e

# Add this line (runs at 9 PM daily)
0 21 * * * /mnt/d/projects/notion_journal/run_from_wsl.sh
```

Create `run_from_wsl.sh`:
```bash
#!/bin/bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate notion-journal
cd /mnt/d/projects/notion_journal
python notion_journal.py
```

## What Gets Tracked

The script tracks:

- **Local Git Commits**: All commits made today in your project directories
  - Commit hash, message, author, date
  - Files changed
  - Repository name

- **GitHub Commits**: Commits pushed to GitHub today
  - Commit hash, message, repository
  - Links to commits on GitHub

- **Summary Statistics**:
  - Total commits
  - Number of repositories worked on

## Journal Entry Structure

Each journal entry includes:

1. **Daily Summary**: Total commits and repositories
2. **Local Commits**: Organized by repository
3. **GitHub Commits**: With links to GitHub
4. **Notes Section**: For manual notes and reflections

## Troubleshooting

### Script can't find Notion database
- Verify database ID is correct (from URL)
- Make sure database is shared with your integration

### No commits found
- Check that your projects are git repositories
- Verify git is configured: `git config --global user.name` and `git config --global user.email`
- Make sure you made commits today

### GitHub commits not showing
- Verify GitHub token has correct permissions
- Check that your username is correct
- Ensure commits were pushed to GitHub today

### Task Scheduler not running
- Check Task Scheduler logs
- Verify Python path is correct (use full path to conda python)
- Test script manually first
- Check that `.env` file is readable

## Customization

You can customize the script by editing `notion_journal.py`:

- Add more project paths
- Change journal entry format
- Add additional tracking (e.g., file changes, time tracking)
- Filter specific repositories
- Add custom tags or properties

## License

MIT License - feel free to use and modify for your needs!
