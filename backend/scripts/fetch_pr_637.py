
import asyncio
import os
import sys
import json
import uuid

# Add the backend directory to sys.path to resolve imports correctly
sys.path.append(os.path.abspath('.'))

from connectors.github import GitHubConnector
from models.database import get_session

async def fetch_pr_details():
    org_id = "dbe0b687-6967-4874-a26d-10f6289ae350"
    repo_full_name = "basebase-ai/basebase"
    pr_number = "637"
    
    connector = GitHubConnector(organization_id=org_id)
    try:
        pr_data = await connector.query(f"pr:{pr_number} repo:{repo_full_name}")
        print(json.dumps(pr_data, indent=2))
    except Exception as e:
        print(f"Error fetching PR: {e}")

if __name__ == "__main__":
    asyncio.run(fetch_pr_details())
