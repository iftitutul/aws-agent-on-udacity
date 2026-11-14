Location: AWS Console (no code changes required)

In this phase, you will create three Bedrock Knowledge Bases — one per policy domain. These are the data sources that power the parallel multi-agent RAG system you built in Phase 1.
Background: Bedrock Knowledge Bases with S3 Vectors

A Knowledge Base is a managed RAG service — point it at an S3 prefix and Bedrock handles chunking, embedding (Titan Embed Text v2), and vector indexing into S3 Vectors (serverless, no OpenSearch needed). S3 Vectors is a separate service from general-purpose S3: a Knowledge Base needs a vector bucket and one vector index per KB. Your CloudFormation stack created both — run python config.py to see their names. The bedrock-agent-runtime.retrieve() API returns the top-k relevant passages. See: Bedrock Knowledge Bases(opens in a new tab)
Step 1: Verify policy documents

The policy documents were uploaded to S3 when you ran seed_data.py during environment setup. They are organized under three prefixes:

s3://{policy-docs-bucket}/policies/returns/    ← returns policy documents
s3://{policy-docs-bucket}/policies/shipping/   ← shipping policy documents
s3://{policy-docs-bucket}/policies/warranty/   ← warranty policy documents

You can verify in the AWS Console:

    Navigate to AWS Console → S3
    Open the bucket named udacity-agentcore-policy-docs-{ACCOUNT_ID}-{suffix} (the exact name is the Policy Bucket line of python config.py)
    Navigate to the policies/ prefix
    Verify you see three folders: returns/, shipping/, warranty/, each containing policy documents

Alternatively, in AWS CloudShell (browser-based shell with AWS CLI pre-installed):

aws s3 ls s3://$(python -c "import config; print(config.POLICY_BUCKET)")/policies/ --recursive

Step 2: Create three Knowledge Bases in the AWS Console

Navigate to: AWS Console → Amazon Bedrock → Knowledge Bases → Create Knowledge Base

Create three KBs with these settings (one per domain):
Setting	Returns KB	Shipping KB	Warranty KB
Name	novamart-returns-policy-kb	novamart-shipping-policy-kb	novamart-warranty-policy-kb
S3 data source prefix	policies/returns/	policies/shipping/	policies/warranty/
Embedding model	Amazon Titan Embed Text v2	Amazon Titan Embed Text v2	Amazon Titan Embed Text v2
Vector store	S3 Vectors → Use an existing vector bucket	same	same
S3 Vectors bucket	Vector Bucket from python config.py (udacity-agentcore-vectors-…)	same	same
Vector index	returns-policy-index	shipping-policy-index	warranty-policy-index

Do not choose Managed KB — that creates a different vector bucket than the one the project (and the rubric) expects, and the backing store cannot be changed afterwards. Use Self-managed KBs.

After creating each KB, click Sync to index the documents.
Step 3: Add KB IDs to your .env

Copy each Knowledge Base ID from the console and add to your .env:

RETURNS_KB_ID=<your-returns-kb-id>
SHIPPING_KB_ID=<your-shipping-kb-id>
WARRANTY_KB_ID=<your-warranty-kb-id>

Test your work

python tests/test_agent.py task5

Tips

    After creating a KB, you MUST click "Sync" before queries will return results
    If retrieval returns empty results, check that your KB IDs in .env match the console
    The S3 Vectors bucket and the three indexes were already created by the CloudFormation stack you deployed earlier; python tests/test_agent.py task5 reports which vector store each KB uses