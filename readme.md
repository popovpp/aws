# ABOUT
The repository containes the AWS lambda functions that does follow activities:
1) it checks new works on the website http://samlib.ru/editors/p/popow_p_p/;
2) if new works are there then it gets a text from every new work, saves the text as a file into s3 storage, make a record into MongoDB and sends a message to telegram channel.
3) the lambda functions is invoked 1 time per day according with schedule.

## How to deploy lambda

Quick overview — your options

Zip + AWS CLI — package code + deps into function.zip and run aws lambda update-function-code. (Recommended for small projects.)

Upload zip to S3 + AWS CLI — useful for large packages or CI.

Lambda Layers — put heavy dependencies into a layer, keep function zip small.

AWS Console → Upload — manual UI upload (ok for quick edits).

SAM / Serverless / Container image — more advanced infra-as-code / reproducible builds for production.

I’ll show (1), (2), (3) and the Console in detail.

## A. Prepare your project locally (requirements, venv)

Recommended structure:

`project/
  lambda_function.py
  requirements.txt
  package/        # created during packaging
  function.zip`


Create & activate a virtualenv (Linux/macOS):

`python -m venv venv
source venv/bin/activate`


Windows PowerShell:

`python -m venv venv
.\venv\Scripts\Activate.ps1`


Put dependencies into requirements.txt (example):

requests
beautifulsoup4
pymongo
boto3

## B. Method 1 — Zip + AWS CLI (local packaging & upload)

This is the standard method when you edit code and want to push it.

1) Install dependencies into a package/ folder

This bundles dependencies with your handler file. Run from project root:

ensure venv is active
`pip install -r requirements.txt -t ./package`


Notes:

`-t ./package installs packages into package/ directory (no site-packages links).

If a dependency has C extensions (compiled code), you must build it for Amazon Linux (see “Native/C dependencies” below).`

2) Copy your lambda file into package and create zip
`cp lambda_function.py package/
cd package
zip -r ../function.zip .
cd ..`
function.zip now contains dependencies + lambda_function.py


Windows (PowerShell) alternative:

`Copy-Item lambda_function.py package\
Set-Location package
Compress-Archive -Path * -DestinationPath ..\function.zip
Set-Location ..`

3) Upload to Lambda with AWS CLI
`aws lambda update-function-code \
  --function-name popow-scraper \
  --zip-file fileb://function.zip \
  --region eu-central-1`


fileb:// is required for binary files.

After this completes, AWS Lambda will run your new code.

4) (Optional) publish new version
`aws lambda publish-version --function-name popow-scraper --region eu-central-1`

5) Test the function

Invoke a test payload:

`aws lambda invoke \
  --function-name popow-scraper \
  --payload '{}' \
  response.json \
  --region eu-central-1`

view response
cat response.json

6) View logs (very useful)
stream logs (AWS CLI v2 recommended)
`aws logs tail /aws/lambda/popow-scraper --follow --region eu-central-1`

## C. Method 2 — Upload zip to S3 then instruct Lambda to use it

Use this when zip is large or for CI pipelines.

Upload to S3:

aws s3 cp function.zip s3://your-deploy-bucket/path/function.zip --region eu-central-1


Update Lambda to use S3 object:

aws lambda update-function-code \
  --function-name popow-scraper \
  --s3-bucket your-deploy-bucket \
  --s3-key path/function.zip \
  --region eu-central-1


Why use S3?

Large packages (zipped > 50 MB) must use S3.

Useful if you want to reuse artifacts or do CI/CD.

## D. Method 3 — Use Lambda Layers for heavy dependencies (recommended long term)

If pymongo or other deps are large, put them into a layer so you only upload function code each edit.

1) Build a layer package

Create python/ directory that contains packages at python/lib/python3.x/site-packages/ when needed for some setups; but a simple python top-level is accepted for Python runtimes:

create a clean folder for layer
`mkdir layer
pip install -r requirements.txt -t layer/python
cd layer
zip -r ../layer.zip .
cd ..`

2) Publish layer
`aws lambda publish-layer-version \
  --layer-name popow-deps \
  --zip-file fileb://layer.zip \
  --compatible-runtimes python3.11 \
  --description "Dependencies for popow-scraper"`


This returns an ARN like `arn:aws:lambda:eu-central-1:123456789012:layer:popow-deps:1`.

3) Attach layer to function
`aws lambda update-function-configuration \
  --function-name popow-scraper \
  --layers arn:aws:lambda:eu-central-1:123456789012:layer:popow-deps:1`


After that, your function zip only needs to include lambda_function.py (no deps), making updates small and fast.

## E. Method 4 — Upload via AWS Console (manual)

Good for tiny edits or quick experiments.

Go to AWS Console → Lambda → Functions → select popow-scraper.

In Code tab, choose Upload from → .zip file → upload function.zip.

Click Deploy (or Save).

Test with Test button or check logs.

Caveats:

Console inline editor only works for small single-file changes (and you can't install packages there).

Manual and not repeatable for CI.

## F. Advanced — Container image (short summary)

If you prefer Docker images:

Build image with your code + deps.

Push to ECR and update Lambda with --package-type Image --code ImageUri=....
This is great when you have complex native dependencies or need custom base OS.

## G. Native/C dependencies (very important)

If a pip package contains compiled C code (wheels), they must be built for Amazon Linux environment (the same that Lambda uses). If you pip install on your laptop (macOS or Ubuntu), those compiled artifacts may be incompatible.

Solutions:

Build in an Amazon Linux Docker container:

`docker run --rm -v "$PWD":/var/task amazonlinux:2 /bin/bash -c "\
  yum install -y python3 python3-devel gcc gcc-c++ unzip && \
  python3 -m pip install --upgrade pip && \
  python3 -m pip install -r requirements.txt -t /var/task/package"`


(there are community images lambci/lambda:build-python3.11 that mimic Lambda build env — they simplify this.)

Use Lambda Layers built on Amazon Linux, as shown above.

## H. Permissions required for deployment

Your IAM user (the one configuring AWS CLI) needs:

lambda:UpdateFunctionCode, lambda:UpdateFunctionConfiguration, lambda:PublishVersion (if publishing)

s3:PutObject / s3:GetObject if using S3 artifact uploads

iam:PassRole if updating function configuration with a role

If you get AccessDenied, attach appropriate policies to your IAM user or use an admin user (for learning).

## I. Typical workflow (repeatable bash script)

Create deploy.sh to automate packaging & upload (Linux/macOS):

`#!/usr/bin/env bash
set -e

FUNC_NAME="popow-scraper"
REGION="eu-central-1"
BUCKET=""   # optional: set if you want S3 upload

echo "Cleaning old package..."
rm -f function.zip
rm -rf package
mkdir -p package

echo "Installing dependencies..."
pip install -r requirements.txt -t package

echo "Copying lambda code..."
cp lambda_function.py package/

echo "Creating zip..."
cd package
zip -r ../function.zip .
cd ..

if [ -z "$BUCKET" ]; then
  echo "Updating Lambda directly..."
  aws lambda update-function-code --function-name "$FUNC_NAME" --zip-file fileb://function.zip --region "$REGION"
else
  KEY="deploys/${FUNC_NAME}_$(date +%Y%m%d%H%M%S).zip"
  echo "Uploading to s3://$BUCKET/$KEY"
  aws s3 cp function.zip s3://"$BUCKET"/"$KEY" --region "$REGION"
  echo "Updating Lambda from S3..."
  aws lambda update-function-code --function-name "$FUNC_NAME" --s3-bucket "$BUCKET" --s3-key "$KEY" --region "$REGION"
fi

echo "Published. You can check logs with:"
echo "aws logs tail /aws/lambda/$FUNC_NAME --follow --region $REGION"`


Make it executable:

`chmod +x deploy.sh
./deploy.sh`


This automates the exact steps above.

## J. Post-deploy: verify and debug

Invoke function to see immediate output:

`aws lambda invoke --function-name popow-scraper --payload '{}' response.json --region eu-central-1
cat response.json`


Watch logs:

`aws logs tail /aws/lambda/popow-scraper --follow --region eu-central-1`


Check errors: Common issues are ModuleNotFoundError (forgot to include dependency), NoSuchBucket (wrong bucket name/region), or permission denied.

## K. Best practices & tips

Use version control (git) for code. Tag releases, keep requirements.txt updated.

Use Lambda Layers for common deps to speed deployments.

Use SAM / CI/CD when you want reproducible builds and automatic deployments.

Keep your handler code small — keep large logic in modules or external services.

Use environment variables / SSM for secrets — don’t hardcode tokens.

Test locally with the same Python version as Lambda (e.g., 3.11) and consider using Docker to emulate runtime for compiled packages.

Publish versions + aliases for safe rollouts:

`aws lambda publish-version → returns version number` (e.g., 2)

`aws lambda create-alias --function-name popow-scraper --name prod --function-version 2`

`Update alias to point a new version after testing`.

## L. If you run into problems — quick checklist

Did function.zip actually include lambda_function.py? (zipinfo function.zip)

Are dependencies present inside the zip (package/requests, package/pymongo)?

Does your Lambda runtime match your local Python version? (3.11 vs 3.10)

If you used compiled packages, were they built for Amazon Linux?

Does the IAM user running aws lambda update-function-code have lambda:UpdateFunctionCode?

If using S3 upload, is the bucket name correct and in the same region?

Check CloudWatch logs for stack traces.


# CHECKING TOOLS

## ✅1. Check that AWS accepted your new code

Run:

`aws lambda get-function --function-name popow-scraper --region eu-central-1`


This shows details:

LastModified → should match the time you uploaded.

CodeSize → should reflect your function.zip.

## ✅ 2. Invoke your Lambda manually

This proves it actually runs on AWS infrastructure.

`aws lambda invoke \
  --function-name popow-scraper \
  --payload '{}' \
  response.json \
  --region eu-central-1`


If it runs successfully, response.json will contain your function’s return value.

If it errors, you’ll see an exception, and CloudWatch logs will have details.

Inspect the output:

`cat response.json`

## ✅ 3. Watch logs in CloudWatch

Lambda automatically writes logs. Run:

`aws logs tail /aws/lambda/popow-scraper --follow --region eu-central-1`


This streams logs in real time.

If you just invoked manually, you’ll see logs from that execution (print statements, errors, etc.).

## ✅ 4. Check that your EventBridge schedule works

If you already created the EventBridge (cron) rule:

`aws events list-targets-by-rule \
  --rule popow-schedule \
  --region eu-central-1`


→ Should show your Lambda as a target.

Then wait until the scheduled time (e.g., once per day) and confirm new log entries in CloudWatch.

## ✅ 5. Confirm side effects

Since your Lambda:

Sends messages to Telegram

Saves .txt to S3

Writes to MongoDB

You should also check:

Your Telegram channel → is there a new post?

Your S3 bucket → run

`aws s3 ls s3://popow-lyrics-storage --region eu-central-1`


Do you see new .txt files?

Your MongoDB Atlas → open MongoDB Atlas UI → Collections → does lyricsdb have new docs?

👉 With these checks, you can be 100% sure your Lambda is running in AWS and doing its job.


# Deploying by SAM

## 1) template.yaml
`AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Popow Lyrics Scraper Lambda (SAM)

Globals:
  Function:
    Runtime: python3.11
    Timeout: 120
    MemorySize: 256

Resources:

  PopowLyricsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: popow-lyrics-storage  # change if this name is taken
    DeletionPolicy: Retain

  PopowScraperFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: popow-scraper
      CodeUri: src/
      Handler: lambda_function.lambda_handler
      Environment:
        Variables:
          # These are the SSM parameter names (Lambda will read actual values at runtime)
          SSM_MONGO_PARAM: "/popow/mongo_uri"
          SSM_TELEGRAM_PARAM: "/popow/telegram_token"
          TELEGRAM_CHAT_ID_PARAM: "/popow/telegram_chat_id"
          S3_BUCKET: !Ref PopowLyricsBucket
          AUTHOR_PAGE: "http://samlib.ru/editors/p/popow_p_p/"
      Events:
        DailySchedule:
          Type: Schedule
          Properties:
            Schedule: rate(1 day)

      # Minimal inline permissions:
      Policies:
        - Statement:
            Effect: Allow
            Action:
              - ssm:GetParameter
              - ssm:GetParameters
            Resource: "arn:aws:ssm:*:*:parameter/popow/*"
          Version: "2012-10-17"
        - Statement:
            Effect: Allow
            Action:
              - s3:PutObject
              - s3:GetObject
              - s3:ListBucket
            Resource:
              - !Sub "arn:aws:s3:::${PopowLyricsBucket}"
              - !Sub "arn:aws:s3:::${PopowLyricsBucket}/*"
          Version: "2012-10-17"
        - Statement:
            Effect: Allow
            Action:
              - logs:CreateLogGroup
              - logs:CreateLogStream
              - logs:PutLogEvents
            Resource: "arn:aws:logs:*:*:*"
          Version: "2012-10-17"

Outputs:
  FunctionName:
    Description: Name of the lambda function
    Value: !Ref PopowScraperFunction
  S3Bucket:
    Description: Bucket storing .txt files
    Value: !Ref PopowLyricsBucket`


Notes:

Change BucketName if popow-lyrics-storage is already taken (S3 bucket names are global).

The inline Policies above allow:

read access to SSM parameters under /popow/*

minimal S3 write/read on the specific bucket

CloudWatch logs

DeletionPolicy: Retain keeps S3 bucket if stack is deleted (safe).

## 2) src/lambda_function.py

Save this as src/lambda_function.py.

## 3) requirements.txt
requests==2.31.0
beautifulsoup4==4.12.2
pymongo==4.5.1
dnspython==2.3.0
boto3==1.26.0


Pin versions for reproducible builds. Adjust versions as you like.

dnspython is often required for mongodb+srv URIs.

## 4) How to prepare secrets in SSM Parameter Store

Create three parameters (use AWS Console or CLI). Example CLI:

`aws ssm put-parameter \
  --name /popow/mongo_uri \
  --value "mongodb+srv://lyrics_user:YourPass123@cluster0.xxxxx.mongodb.net/lyricsdb?retryWrites=true&w=majority" \
  --type "SecureString" --overwrite --region eu-central-1`

`aws ssm put-parameter \
  --name /popow/telegram_token \
  --value "123456789:ABCdefGhIj..." \
  --type "SecureString" --overwrite --region eu-central-1`

`aws ssm put-parameter \
  --name /popow/telegram_chat_id \
  --value "-1001234567890" \
  --type "String" --overwrite --region eu-central-1`


Important:

For MongoDB Atlas connection string include the DB name (/lyricsdb) so get_database() works.

For Telegram chat id use numeric ID (channels often start with -100...) or @channelusername for public channels.

## 5) MongoDB Atlas: whitelist & user

In Atlas UI → Network Access → add IP whitelist entry. For Lambda you can:

For development/testing: temporarily 0.0.0.0/0 (open access) — not recommended for production.

For production: use Atlas VPC peering or restrict to NAT/Elastic IPs used by your VPC.

Create a DB user (Database Access → Add New Database User) and use that username/password in the MONGO_URI.

## 6) Build & deploy steps (SAM)

Install SAM CLI (per your OS). Ensure Docker is installed and running (for --use-container).

From repo root:

- build (container ensures compatibility)
s`am build --use-container`

- first-time deploy guided
`sam deploy --guided`


During guided deploy:

Choose stack name (e.g., popow-scraper-stack)

Confirm region eu-central-1

Accept creation of IAM roles & capabilities (CAPABILITY_IAM) if prompted

Save the configuration for future sam deploy

Subsequent deploy:

`sam deploy`

## 7) Testing & verification

After deploy, check S3 for test or real saved files:

`aws s3 ls s3://popow-lyrics-storage --region eu-central-1`


Check Lambda logs:

`aws logs tail /aws/lambda/popow-scraper --follow --region eu-central-1`


Check MongoDB Atlas Collections → lyricsdb → works for inserted docs.

Check Telegram channel for posts.

## 8) Notes, caveats & best practices

Build environment — use sam build --use-container so compiled deps (if any) are built for Amazon Linux.

Network access to Atlas — if Lambda is in a VPC with no internet, it cannot reach Atlas unless you configure NAT or VPC peering. Avoid placing Lambda inside VPC unless necessary.

SSM permissions — SAM template above grants ssm:GetParameter for /popow/*. Keep parameter names consistent.

Rate limiting — the code sleeps 2s between publish attempts to avoid Telegram flood limits. Adjust if needed.

Robustness — consider adding retries with exponential backoff for network calls & transient Mongo errors.

Monitoring — add CloudWatch Alarms for Errors / high duration.

Security — rotate MongoDB credentials, and narrow SSM parameter resource ARNs if you harden policies. Use OIDC for CI (GitHub Actions) as we discussed earlier.

Bucket names — must be globally unique. Change popow-lyrics-storage if conflict occurs.

## 9) Quick checklist before first deploy

 Update template.yaml bucket name if needed.

 Populate SSM /popow/mongo_uri, /popow/telegram_token, /popow/telegram_chat_id.

 Ensure MongoDB Atlas user/password in URI and Atlas network whitelist is OK.

 Confirm your Telegram bot is admin of the channel.

 Run sam build --use-container then sam deploy --guided.
 