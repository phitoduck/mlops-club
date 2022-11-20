# This is a "Justfile". "just" is a task-runner similar to "make", but much less frustrating.
# There is a VS Code extension for just that provides syntax highlighting.
#
# Execute any commands in this file by running "just <command name>", e.g. "just install".

AWS_PROFILE := "mlops-club"
AWS_REGION := "us-west-2"

# install the project's python packages and other useful
install: require-venv
    # install useful VS Code extensions
    which code && code --install-extension njpwerner.autodocstring
    which code && code --install-extension kokakiwi.vscode-just
    # install python packages not belonging to any particular package in this repo,
    # but important for development
    python -m pip install \
        pre-commit \
        phitoduck-projen \
        black \
        pylint \
        flake8 \
        mypy
    # install the metaflow-deployment package as an "editable" package
    python -m pip install -r ./awscdk-metaflow/requirements-dev.txt
    # install pre-commit hooks to protect the quality of code committed by contributors
    pre-commit install
    # install git lfs for downloading rootski CSVs and other large files in the repo
    git lfs install

cdk-deploy: require-venv
    cd awscdk-metaflow \
    && \
        AWS_PROFILE={{AWS_PROFILE}} \
        CDK_DEFAULT_REGION={{AWS_REGION}} \
        AWS_REGION={{AWS_REGION}} \
        cdk deploy --all --diff --profile {{AWS_PROFILE}} --require-approval any-change --region {{AWS_REGION}}

cdk-destroy: require-venv
    cd awscdk-metaflow \
    && \
        AWS_PROFILE={{AWS_PROFILE}} \
        CDK_DEFAULT_REGION={{AWS_REGION}} \
        cdk destroy --all --diff --profile {{AWS_PROFILE}} --region {{AWS_REGION}}

# generate CloudFormation from the code in "awscdk-metaflow"
cdk-synth: require-venv login-to-aws
    cd awscdk-metaflow \
    && cdk synth --all --profile mlops-club

open-aws:
    #!/bin/bash
    MLOPS_CLUB_SSO_START_URL="https://d-926768adcc.awsapps.com/start"
    open $MLOPS_CLUB_SSO_START_URL

# Ensure that an "mlops-club" AWS CLI profile is configured. Then go through an AWS SSO
# sign in flow to get temporary credentials for that profile. If this command finishes successfully,
# you will be able to run AWS CLI commands against the MLOps club account using '--profile mlops-club'
login-to-aws:
    #!/bin/bash
    MLOPS_CLUB_AWS_PROFILE_NAME="mlops-club"
    MLOPS_CLUB_AWS_ACCOUNT_ID="630013828440"
    MLOPS_CLUB_SSO_START_URL="https://d-926768adcc.awsapps.com/start"
    MLOPS_CLUB_SSO_REGION="us-west-2"

    # skip if already logged in
    # aws sts get-caller-identity --profile ${MLOPS_CLUB_AWS_PROFILE_NAME} | cat | grep 'UserId' > /dev/null \
    #     && echo "[mlops-club] ✅ Logged in with aws cli" \
    #     && exit 0

    # configure an "[mlops-club]" profile in aws-config
    echo "[mlops-club] Configuring an AWS profile called '${MLOPS_CLUB_AWS_PROFILE_NAME}'"
    aws configure set sso_start_url ${MLOPS_CLUB_SSO_START_URL} --profile ${MLOPS_CLUB_AWS_PROFILE_NAME}
    aws configure set sso_region ${MLOPS_CLUB_SSO_REGION} --profile ${MLOPS_CLUB_AWS_PROFILE_NAME}
    aws configure set sso_account_id ${MLOPS_CLUB_AWS_ACCOUNT_ID} --profile ${MLOPS_CLUB_AWS_PROFILE_NAME}
    # aws configure set sso_role_name AdministratorAccess --profile ${MLOPS_CLUB_AWS_PROFILE_NAME}
    aws configure set region ${MLOPS_CLUB_SSO_REGION} --profile ${MLOPS_CLUB_AWS_PROFILE_NAME}

    # login to AWS using single-sign-on
    aws sso login --profile ${MLOPS_CLUB_AWS_PROFILE_NAME} \
    && echo '' \
    && echo "[mlops-club] ✅ Login successful. AWS CLI commands will now work by adding the '--profile ${MLOPS_CLUB_AWS_PROFILE_NAME}' 😃" \
    && echo "             Your '${MLOPS_CLUB_AWS_PROFILE_NAME}' profile has temporary credentials using this identity:" \
    && echo '' \
    && aws sts get-caller-identity --profile ${MLOPS_CLUB_AWS_PROFILE_NAME} | cat
    
# certain boilerplate files like setup.cfg, setup.py, and .gitignore are "locked";
# you can modify their contents by editing the .projenrc.py file in the root of the repo.
update-boilerplate-files: require-venv
    python .projenrc.py

# throw an error if a virtual environment isn't activated;
# add this as a requirement to other targets that you want to ensure always run in
# some kind of activated virtual environment
require-venv:
    #!/usr/bin/env python
    import sys
    from textwrap import dedent

    def get_base_prefix_compat():
        """Get base/real prefix, or sys.prefix if there is none."""
        return getattr(sys, "base_prefix", None) or getattr(sys, "real_prefix", None) or sys.prefix

    def in_virtualenv():
        return get_base_prefix_compat() != sys.prefix

    if not in_virtualenv():
        print(dedent("""\
            ⛔️ ERROR: 'just' detected that you have not activated a python virtual environment.

            Science has shown that installing python packages (e.g. 'pip install pandas')
            without a virtual environment increases likelihood of getting ulcers and COVID. 🧪👩‍🔬

            To resolve this error, please activate a virtual environment by running
            whichever of the following commands apply to you:

            ```bash
            # create a (virtual) copy of the python just for this project
            python -m venv ./venv/

            # activate that copy of python (now 'which python' points to your new virtual copy)
            source ./venv/bin/activate

            # re-run whatever 'just' command you just tried to run, for example
            just install
            ```

            -- Sincerely, The venv police 👮 🐍
        """))

        sys.exit(1)

    print("[mlops-club] ✅ Virtual environment is active")


# run the metaflow frontend and backend locally using docker-compose;
# refer to the docker-compose.mlops-club.yml file for container details;
# you could use PGAdmin or DBeaver to connect to the local database and
# explore the data that metaflow stores in the database
run-local-metaflow: fetch-metaflow-source
    #!/bin/bash

    function build_images() {
        cd ./metaflow-repos/metaflow-service && docker-compose -f docker-compose.mlops-club.yml build && cd ../..
    }
    
    # prepare our custom docker compose that runs the UI as well as the backend
    cp docker-compose.mlops-club.yml ./metaflow-repos/metaflow-service/

    # build images if they are not already built
    docker images | grep metaflow-service-ui > /dev/null || build_images
    docker images | grep metaflow-service-ui_backend > /dev/null || build_images
    docker images | grep metaflow-service-metadata > /dev/null || build_images
    docker images | grep metaflow-service-migration > /dev/null || build_images

    echo "[mlops-club] 🐳 All docker images are built"

    # run the services
    cd ./metaflow-repos/metaflow-service && docker-compose -f docker-compose.mlops-club.yml up

# clone the github repos for the metaflow frontend and backend
fetch-metaflow-source:
    #!/bin/bash
    mkdir -p metaflow-repos
    cd ./metaflow-repos
    [[ -d ./metaflow-ui ]] || git clone https://github.com/Netflix/metaflow-ui.git
    [[ -d ./metaflow-service ]] || git clone https://github.com/Netflix/metaflow-service.git
    echo "[mlops-club] ✅ metaflow-ui and metaflow-service repos are present"

# run a local python file with a FlowSpec inside; this is run against the
# local docker-compose metaflow setup, so you'll need to run 'just run-local-metaflow'
# before this command will work.
#
# Note that the metaflow CLI prioritizes environment variables over values
# defined in the ~/.metaflowconfig/config.json file. If you want to know what
# the various env vars are and how they work, simply run "metaflow configure aws"
# which is a wizard that walks you through setup of that file
run-sample-flow: require-venv
    #!/bin/bash

    export METAFLOW_S3_ENDPOINT_URL=http://localhost:9000  # minio
    export AWS_ACCESS_KEY_ID=minio-root-user
    export AWS_SECRET_ACCESS_KEY=minio-root-password

    export METAFLOW_DATASTORE_SYSROOT_S3=s3://minio-metaflow-bucket/metaflow/
    export METAFLOW_DATATOOLS_SYSROOT_S3=s3://minio-metaflow-bucket/metaflow/data
    export METAFLOW_DEFAULT_DATASTORE=s3
    export METAFLOW_DEFAULT_METADATA=service
    export METAFLOW_SERVICE_AUTH_KEY=iigKSNbmWb4To3dWBgmE17KyHcFyxEAn5NlU5aR8
    export METAFLOW_SERVICE_INTERNAL_URL=http://localhost:8083/api/
    export METAFLOW_SERVICE_URL=http://localhost:8080

    python ./flow.py run

# deploy the version of metaflow offered by the officially maintained CloudFormation template
deploy-cfn-template:
    #!/bin/bash

    cdk deploy --app 'python ./awscdk-metaflow/cfn_app.py' --profile mlops-club --region {{AWS_REGION}}

    echo "[mlops-club] ✅ Stack deployed. You'll need to run 'metaflow configure aws' and enter outputs from this stack."
    echo "[mlops-club] 📌 Run 'aws apigateway get-api-key --api-key <YOUR_KEY_ID_FROM_CFN> --include-value | grep value'"
    echo "             to get the actual API Gateway key that is needed to to access the metadata service. The"
    echo "             ApiKeyId output is just the Key ID not the actual key."
