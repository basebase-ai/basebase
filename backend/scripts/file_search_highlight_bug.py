import asyncio
import logging
from connectors.linear import LinearConnector

logging.basicConfig(level=logging.INFO)

async def main():
    # Use the organization ID found in tracker_teams
    org_id = "dbe0b687-6967-4874-a26d-10f6289ae350"
    
    connector = LinearConnector(organization_id=org_id)
    
    print(f"Filing bug in Linear for org {org_id}...")
    
    try:
        result = await connector.create_issue(
            team_key="BAS",
            title="Highlight search results in All Chats",
            description="""## Problem
When searching for a term (like "cookie" or "OraClaim") in the All Chats page, the matching conversations are returned, but it's hard to see *why* they matched.

## Proposed Solution
Highlight the matched search term in the search results:
- Highlight matches in the conversation title
- Highlight matches in the AI summary (if visible)
- Highlight matches in the last message preview

This will help users quickly identify the relevance of each search result.""",
            priority=3,  # Medium
            labels=["Bug", "UI/UX"]
        )
        print(f"Successfully created Linear issue: {result.get('identifier')}")
        print(f"URL: {result.get('url')}")
    except Exception as e:
        print(f"Failed to create Linear issue: {e}")

if __name__ == "__main__":
    asyncio.run(main())
