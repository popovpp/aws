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
mkdir layer
pip install -r requirements.txt -t layer/python
cd layer
zip -r ../layer.zip .
cd ..

2) Publish layer
aws lambda publish-layer-version \
  --layer-name popow-deps \
  --zip-file fileb://layer.zip \
  --compatible-runtimes python3.11 \
  --description "Dependencies for popow-scraper"


This returns an ARN like arn:aws:lambda:eu-central-1:123456789012:layer:popow-deps:1.

3) Attach layer to function
aws lambda update-function-configuration \
  --function-name popow-scraper \
  --layers arn:aws:lambda:eu-central-1:123456789012:layer:popow-deps:1


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

docker run --rm -v "$PWD":/var/task amazonlinux:2 /bin/bash -c "\
  yum install -y python3 python3-devel gcc gcc-c++ unzip && \
  python3 -m pip install --upgrade pip && \
  python3 -m pip install -r requirements.txt -t /var/task/package"


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

#!/usr/bin/env bash
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
echo "aws logs tail /aws/lambda/$FUNC_NAME --follow --region $REGION"


Make it executable:

chmod +x deploy.sh
./deploy.sh


This automates the exact steps above.

## J. Post-deploy: verify and debug

Invoke function to see immediate output:

aws lambda invoke --function-name popow-scraper --payload '{}' response.json --region eu-central-1
cat response.json


Watch logs:

aws logs tail /aws/lambda/popow-scraper --follow --region eu-central-1


Check errors: Common issues are ModuleNotFoundError (forgot to include dependency), NoSuchBucket (wrong bucket name/region), or permission denied.

## K. Best practices & tips

Use version control (git) for code. Tag releases, keep requirements.txt updated.

Use Lambda Layers for common deps to speed deployments.

Use SAM / CI/CD when you want reproducible builds and automatic deployments.

Keep your handler code small — keep large logic in modules or external services.

Use environment variables / SSM for secrets — don’t hardcode tokens.

Test locally with the same Python version as Lambda (e.g., 3.11) and consider using Docker to emulate runtime for compiled packages.

Publish versions + aliases for safe rollouts:

aws lambda publish-version → returns version number (e.g., 2)

aws lambda create-alias --function-name popow-scraper --name prod --function-version 2

Update alias to point a new version after testing.

## L. If you run into problems — quick checklist

Did function.zip actually include lambda_function.py? (zipinfo function.zip)

Are dependencies present inside the zip (package/requests, package/pymongo)?

Does your Lambda runtime match your local Python version? (3.11 vs 3.10)

If you used compiled packages, were they built for Amazon Linux?

Does the IAM user running aws lambda update-function-code have lambda:UpdateFunctionCode?

If using S3 upload, is the bucket name correct and in the same region?

Check CloudWatch logs for stack traces.
s