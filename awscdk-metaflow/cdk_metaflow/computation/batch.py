"""
NOTE: apologies for the vague function names in this file which create IAM policies. It
shows that I do not yet understand their purpose. I simply ported them from the original
CloudFormation YAML to CDK.

Various compute environments that can be used with Metaflow.

Metaflow submits "jobs" (mortal docker container processes) to an AWS::Batch::JobQueue.
A job queue then schedules these jobs to run on an a compute environment.

What is a compute environment?
------------------------------

An AWS::Batch::ComputeEnvironment is an ECS cluster. This can be a few things:

- Fargate. AWS Batch will start fargate instances for the job. An underlying ECS cluster probably
  is created to achieve this, but that is abstracted from the user.
- Fargate Spot. Same as above, but jobs may get shut down randomly. Comes with a 70% discount.
- Managed EC2. You give AWS Batch a "LaunchTemplate" which defines what types of EC2 instances
  should be provisioned and how many. AWS will scale these instances as needed. This probably
  also uses ECS, but under the hood.
- Unmanaged EC2. You create an EC2-backed ECS cluster yourself and register it as a compute environment.
  You could use this option with ECS-anywhere to schedule AWS Batch jobs on on-premise hardware.
- EKS

A job queue can actually be configured to deploy into one of multiple compute environments,
based on which one has the lowest (most important) priority AND is not at capacity.

What are Metaflow's requirements for a compute environment?
-----------------------------------------------------------

- if you rely on an INTERNAL_METAFLOW_SERVICE_URL, a URL to the metadata service only
  accessible from within the same VPC as the metadata service, then the compute environment
  will need to use that VPC (or a VPC paired to that VPC)
- the ~/.metaflowconfig/config.json file should be configured with the JOB_QUEUE or
  that value should be set as an environment variable

From the ``metaflow configure aws`` command:

```
Metaflow can scale your flows by executing your steps on AWS Batch.
AWS Batch is a strict requirement if you intend to schedule your flows on AWS Step Functions.
Would you like to configure AWS Batch as your compute backend? [y/N]: y
[METAFLOW_BATCH_JOB_QUEUE] AWS Batch Job Queue.: abc
[METAFLOW_ECS_S3_ACCESS_IAM_ROLE] IAM role for AWS Batch jobs to access AWS resources (Amazon S3 etc.).: abc
[METAFLOW_BATCH_CONTAINER_REGISTRY] (optional) Default Docker image repository for AWS Batch jobs. If nothing is specified, dockerhub (hub.docker.com/) is used as default. []: abc
[METAFLOW_BATCH_CONTAINER_IMAGE] (optional) Default Docker image for AWS Batch jobs. If nothing is specified, an appropriate python image is used as default. []: abc
```
"""

from aws_cdk import aws_batch_alpha as batch
from aws_cdk import aws_ec2 as ec2
from constructs import Construct
from typing import List, Optional

from cdk_metaflow.utils import make_namer_fn, TNamerFn


def make_fargate_compute_environment(
    scope: Construct,
    id_prefix: str,
    vpc_with_metadata_service: ec2.Vpc,
) -> batch.ComputeEnvironment:
    make_id: TNamerFn = make_namer_fn(id_prefix)
    return batch.ComputeEnvironment(
        scope,
        id=make_id("fargate-compute-environment"),
        service_role=None,
        compute_resources=batch.ComputeResources(
            type=batch.ComputeResourceType.FARGATE,
            vpc=vpc_with_metadata_service,
            maxv_cpus=8,
        ),
    )


def make_batch_job_queue(
    scope: Construct,
    id_prefix: str,
    compute_environments: List[batch.ComputeEnvironment],
    priority: Optional[int] = 1
) -> batch.JobQueue:
    make_id: TNamerFn = make_namer_fn(id_prefix)
    return batch.JobQueue(
        scope=scope,
        id=make_id("job-queue"),
        enabled=True,
        compute_environments=[
            batch.JobQueueComputeEnvironment(
                compute_environment=comp_env, order=idx + 1
            )
            for idx, comp_env in enumerate(compute_environments)
        ],
        priority=priority,
    )
