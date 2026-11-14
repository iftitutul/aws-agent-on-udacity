Deploy the Foundation Infrastructure

The project includes a CloudFormation stack that provisions the AWS resources your agents will use. You need to deploy this stack before starting any implementation work. You can find the files being referred to below in the workspace above or in the GitHub repo here(opens in a new tab).

The stack (infrastructure/starter_stack.yaml) creates:

    DynamoDB tables: udacity-agentcore-orders, udacity-agentcore-customers, udacity-agentcore-workflow-state
    S3 bucket: for policy documents. The AgentCore CLI stores its deployment package in the CDK bootstrap assets bucket, created on the first runtime deployment.
    S3 Vectors: a vector bucket with three vector indexes (returns-policy-index, shipping-policy-index, warranty-policy-index) — the backing store for the three Knowledge Bases
    IAM role: Execution role for the AgentCore Runtime with permissions for Bedrock, Knowledge Bases, DynamoDB, S3, S3 Vectors, CloudFormation, CloudWatch, and X-Ray
    CloudWatch: Log group for agent execution logs

Deploy the stack

Option A — AWS Console:

    Navigate to AWS Console → CloudFormation → Create stack → With new resources (standard)
    Select Upload a template file → choose infrastructure/starter_stack.yaml → Next
    Stack name: udacity-agentcore → Next
    Leave stack options as defaults → Next
    On the review page, check "I acknowledge that AWS CloudFormation might create IAM resources with custom names"
    Click Submit
    Wait for stack status to reach CREATE_COMPLETE

Option B — AWS CloudShell:

Open AWS Console → CloudShell (bottom-left icon), upload the template file, then run:

aws cloudformation deploy \
  --template-file starter_stack.yaml \
  --stack-name udacity-agentcore \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

    CloudShell is a browser-based shell in the AWS Console with AWS CLI pre-installed — no local setup required.

Wait for the stack to finish deploying. If using CloudShell, you can check the status with:

aws cloudformation describe-stacks \
  --stack-name udacity-agentcore \
  --query "Stacks[0].StackStatus" \
  --region us-east-1

The stack is ready when the status shows CREATE_COMPLETE.
Seed the initial data

After the stack is deployed, seed the DynamoDB tables and S3 bucket with sample data:

python infrastructure/seed_data.py

This populates:

    DynamoDB tables with mock customers (with Standard and Premium tiers) and orders
    S3 policy-docs bucket with sample return, shipping, and warranty policy documents

Configure Environment Variables

cp .env.example .env

Most resource names are loaded automatically from CloudFormation exports — you don't need to fill them in manually. The .env file only holds values that are populated as you complete each task (Knowledge Base IDs, AgentCore Runtime ARN, Guardrail configuration).
Verify Your Setup

python config.py

You should see a configuration table showing all resource names, including the S3 Vectors bucket and index names you will select in Phase 3. Fields showing (not yet created) are expected — they are populated as you complete each task.
Local Machine Instructions

If you prefer to develop on your local machine instead of the workspace:

    Ensure you have Python 3.12+ and the AWS CLI configured with credentials for the us-east-1 region
    Set up a virtual environment:

python -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
pip install -r requirements.txt

    Follow the same CloudFormation deployment and data seeding steps above