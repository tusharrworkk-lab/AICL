Use ACIL project ID: 9e7cd4c5-9ebb-44fb-af26-1a965f7ec4e8.

Before working, call get_execution_context.
If an observable failure occurs, call report_failure_for_review with:
- the failed canonical event
- a concise factual failure summary
- observed actions
- request_bedrock_judgment: true

Never include secrets, raw credentials, source code, or hidden reasoning.