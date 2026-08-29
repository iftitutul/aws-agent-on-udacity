# Cleanup

Order matters. AgentCore resources first, then the S3 objects, then the stacks.

## 1. AgentCore resources

```bash
cd project/starter
python cleanup_agentcore.py          # harness → gateway target → gateway
```

Failures on individual resources are reported but do not stop the run, so a partially torn-down
environment can be finished off by running the script again.

## 2. Empty the evaluation bucket

CloudFormation cannot delete a non-empty bucket — skip this and the testing stack ends in
`DELETE_FAILED`.

```bash
aws s3 rm s3://udacity-agentic-engineer-c1-eval-<ACCOUNT_ID> --recursive --region us-east-1
```

If the stack is already in `DELETE_FAILED`, empty the bucket and re-run the delete below.

## 3. Delete the stacks

```bash
aws cloudformation delete-stack --stack-name bug-report-testing-stack --region us-east-1
aws cloudformation delete-stack --stack-name bug-report-tool-stack    --region us-east-1

aws cloudformation wait stack-delete-complete --stack-name bug-report-tool-stack --region us-east-1
```

## 4. Verify nothing is left

```bash
aws dynamodb list-tables --region us-east-1 | grep bug-report || echo "no tables"
aws lambda list-functions --region us-east-1 --query "Functions[?contains(FunctionName,'bug-report')].FunctionName"
aws iam list-roles --query "Roles[?contains(RoleName,'bug-report')].RoleName"
```

## 5. Local (optional)

```bash
rm -rf project/starter/venv
rm -f  project/starter/agentcore_config.json
```
