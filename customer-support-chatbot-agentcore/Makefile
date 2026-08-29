.DEFAULT_GOAL := help
SHELL := /bin/bash

REGION       ?= us-east-1
TOOL_STACK   ?= bug-report-tool-stack
TEST_STACK   ?= bug-report-testing-stack
STARTER      := project/starter
TESTS_JSON   ?= harness-tests.json
DATASET      ?= output_eval_dataset.jsonl
JOB_NAME     ?= support-chatbot-eval-run-1

BUCKET = $(shell aws cloudformation describe-stacks --stack-name $(TEST_STACK) --region $(REGION) \
	--query "Stacks[0].Outputs[?OutputKey=='EvalDatasetBucketName'].OutputValue" --output text 2>/dev/null)
EVAL_ROLE = $(shell aws cloudformation describe-stacks --stack-name $(TEST_STACK) --region $(REGION) \
	--query "Stacks[0].Outputs[?OutputKey=='BedrockEvalRoleArn'].OutputValue" --output text 2>/dev/null)

.PHONY: help install deploy gateway harness chat dataset deploy-testing upload eval eval-status \
        verify check clean-agentcore clean-stacks clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install dependencies
	cd $(STARTER) && python3 -m venv venv && ./venv/bin/pip install -q -U pip && \
		./venv/bin/pip install -q -r requirements.txt && ./venv/bin/python -c "import boto3;print('boto3',boto3.__version__)"

deploy: ## Deploy the tool stack (DynamoDB + Lambda + IAM)
	aws cloudformation deploy --template-file $(STARTER)/cloudformation-tool.yaml \
		--stack-name $(TOOL_STACK) --capabilities CAPABILITY_NAMED_IAM --region $(REGION)

gateway: ## Create the AgentCore Gateway and register the tool
	cd $(STARTER) && python setup_gateway.py --stack-name $(TOOL_STACK)

harness: ## Create/update the harness from system_prompt.txt (re-run after every prompt edit)
	cd $(STARTER) && python create_harness.py

chat: ## Open an interactive chat session
	cd $(STARTER) && python chat.py --transcript examples/chat_transcript_bug_report.md

dataset: ## Run the test suite and write the JSONL eval dataset
	cd $(STARTER) && python generate-eval-dataset.py --tests-json $(TESTS_JSON) --out $(DATASET)

deploy-testing: ## Deploy the evaluation stack (S3 bucket + eval role)
	aws cloudformation deploy --template-file $(STARTER)/cloudformation-testing.yaml \
		--stack-name $(TEST_STACK) --capabilities CAPABILITY_NAMED_IAM --region $(REGION)
	@echo "bucket: $(BUCKET)"
	@echo "role:   $(EVAL_ROLE)"

upload: ## Upload the dataset to S3
	@test -n "$(BUCKET)" || (echo "testing stack not deployed — run 'make deploy-testing'"; exit 1)
	aws s3 cp $(STARTER)/$(DATASET) s3://$(BUCKET)/$(DATASET) --region $(REGION)

eval: upload ## Create the Bedrock Evaluations job (override JOB_NAME for reruns)
	aws bedrock create-evaluation-job --job-name $(JOB_NAME) --role-arn $(EVAL_ROLE) \
		--evaluation-config '{"automated":{"datasetMetricConfigs":[{"taskType":"General","dataset":{"name":"support-chatbot-eval-dataset","datasetLocation":{"s3Uri":"s3://$(BUCKET)/$(DATASET)"}},"metricNames":["Builtin.Correctness"]}],"evaluatorModelConfig":{"bedrockEvaluatorModels":[{"modelIdentifier":"amazon.nova-pro-v1:0"}]}}}' \
		--inference-config '{"models":[{"precomputedInferenceSource":{"inferenceSourceIdentifier":"my-support-chatbot"}}]}' \
		--output-data-config '{"s3Uri":"s3://$(BUCKET)/results/"}' \
		--region $(REGION)

eval-status: ## Show the status of the evaluation job
	aws bedrock list-evaluation-jobs --region $(REGION) \
		--query 'jobSummaries[?jobName==`$(JOB_NAME)`].[jobName,status]' --output table

verify: ## Show the bug reports the chatbot has filed
	aws dynamodb scan --table-name $(TOOL_STACK)-bug-reports --region $(REGION) --max-items 10 \
		--query 'Items[].{ticket:ticketId.S,status:status.S,created:createdAt.S}' --output table

check: ## Run the offline checks (no AWS calls)
	pytest -q
	cd $(STARTER) && diff -q harness-tests.json flow-tests.json && echo "test files in sync"

clean-agentcore: ## Delete harness, gateway target and gateway
	cd $(STARTER) && python cleanup_agentcore.py

clean-stacks: ## Empty the bucket and delete both stacks
	-aws s3 rm s3://$(BUCKET) --recursive --region $(REGION)
	-aws cloudformation delete-stack --stack-name $(TEST_STACK) --region $(REGION)
	-aws cloudformation delete-stack --stack-name $(TOOL_STACK) --region $(REGION)

clean: clean-agentcore clean-stacks ## Full tear-down
	@echo "Tear-down requested. Watch the stacks with: aws cloudformation describe-stacks --region $(REGION)"
