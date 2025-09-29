import os
from lambda_function import lambda_handler

# set environment variables expected by your code (if you changed the code to read env first)
os.environ['SSM_MONGO_PARAM'] = '/popow/mongo_uri'
# ... or you can modify lambda_function.get_ssm_param to return env vars when available

if __name__ == "__main__":
    print(lambda_handler({}, {}))
