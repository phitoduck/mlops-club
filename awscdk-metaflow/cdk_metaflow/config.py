"""
Configuration for Metaflow.

To arrive at this file, we referenced the official Metaflow CloudFormation template found here:
https://github.com/outerbounds/metaflow-tools/blob/master/aws/cloudformation/metaflow-cfn-template.yml
"""

from dataclasses import dataclass
from typing import ClassVar, Literal, Optional
from pydantic import BaseSettings, conint


@dataclass(frozen=True)
class MetaflowMetadataServiceConstants:
    """Mappings.ServiceInfo section of official Metaflow CloudFormation template."""

    STACK_NAME: ClassVar[str] = "metaflow-infrastructure"
    SERVICE_NAME: ClassVar[str] = "metadata-service-v2"
    IMAGE_URL: ClassVar[str] = "netflixoss/metaflow_metadata_service:v2.2.3"
    CONTAINER_PORT: ClassVar[int] = 8080
    CONTAINER_CPU: ClassVar[int] = 512
    CONTAINER_MEMORY: ClassVar[int] = 1024
    PATH: ClassVar[str] = "*"
    PRIORITY: ClassVar[int] = 1
    DESIRED_COUNT: ClassVar[int] = 1
    ROLE: ClassVar[str] = ""
    HEALTHCHECK_PATH: ClassVar[str] = "/ping"


@dataclass(frozen=True)
class MetaflowUIBackendServiceConstants:
    """Mappings.ServiceInfoUIService section of the official Metaflow CloudFormation template."""

    STACK_NAME: ClassVar[str] = "metaflow-infrastructure"
    SERVICE_NAME: ClassVar[str] = "metaflow-ui-service"
    IMAGE_URL: ClassVar[str] = "netflixoss/metaflow_metadata_service:v2.2.3"
    CONTAINER_PORT: ClassVar[int] = 8083
    CONTAINER_CPU: ClassVar[int] = 512
    CONTAINER_MEMORY: ClassVar[int] = 1024
    # CONTAINER_CPU: ClassVar[int] = 4096
    # CONTAINER_MEMORY: ClassVar[int] = 16384
    PATH: ClassVar[str] = "*"
    PRIORITY: ClassVar[int] = 1
    DESIRED_COUNT: ClassVar[int] = 1
    ROLE: ClassVar[str] = ""
    HEALTHCHECK_PATH: ClassVar[str] = "/api/ping"
    URL_PATH_PREFIX = "/api/"


class MetaflowUIFrontendServiceConstants:
    """Mappings.ServiceInfoUIStatic section of the official Metaflow CloudFormation template."""

    STACK_NAME: ClassVar[str] = "metaflow-infrastructure"
    SERVICE_NAME: ClassVar[str] = "metadata-ui-static"
    IMAGE_URL: ClassVar[str] = "public.ecr.aws/outerbounds/metaflow_ui:v1.1.1"
    CONTAINER_PORT: ClassVar[int] = 3000
    CONTAINER_CPU: ClassVar[int] = 512
    CONTAINER_MEMORY: ClassVar[int] = 1024
    PATH: ClassVar[str] = "*"
    PRIORITY: ClassVar[int] = 1
    DESIRED_COUNT: ClassVar[int] = 1
    ROLE: ClassVar[str] = ""
    HEALTHCHECK_PATH = "/"


class MetaflowStackConfig(BaseSettings):
    """
    Parameters of the official Metaflow CloudFormation template.

    :param sagemaker_instance_type: Instance type for Sagemaker Notebook.
    :param vpc_cidr: CIDR for the Metaflow VPC
    :param subnet_1_cidr: CIDR for Metaflow VPC Subnet 1
    :param subnet_2_cidr: CIDR for Metaflow VPC Subnet 2
    :param max_vcpu_batch: Maximum VCPUs for Batch Compute Environment [16-256]. You can change the upper limit by editing the Cloudformation template
    :param min_vcpu_batch: Minimum VCPUs for Batch Compute Environment [0-16] for EC2 Batch Compute Environment (ignored for Fargate)
    :param desired_vcpu_batch: Desired Starting VCPUs for Batch Compute Environment [0-16] for EC2 Batch Compute Environment (ignored for Fargate)
    :param compute_env_instance_types: The instance types for the compute environment as a comma-separated list
    :param enable_custom_role: CustomRole: Enable custom role with restricted permissions?
    :param enable_api_basic_auth: APIBasicAuth: Enable basic auth for API Gateway? (requires you to export the API key from API Gateway console)
    :param enable_sagemaker: Enable Sagemaker Notebooks
    :param batch_type: AWS Batch compute type
    :param iam_partition: IAM Partition (Select aws-us-gov for AWS GovCloud, otherwise leave as is)
    :param additional_worker_policy_arn: Additional IAM Policy ARN to attach to Batch Compute Environment (leave empty, unless you know what you are doing)
    :param enable_ui: Enable Metaflow UI. Make sure to specify PublicDomainName and CertificateArn if you do
    :param public_domain_name: The custom domain name for UI (e.g., ui.outerbounds.co). Has to match the certificate. Required if UI is enabled
    :param certificate_arn: The ARN of a ACM certificate valid for the custom domain name. Required if UI is enabled
    """

    sagemaker_instance_type: Literal["ml.t2.large", "ml.t2.xlarge", "ml.t2.2xlarge"] = "ml.t2.xlarge"
    """Instance type for Sagemaker Notebook."""

    vpc_cidr: str = "10.20.0.0/16"
    """CIDR for the Metaflow VPC"""

    subnet_1_cidr: str = "10.20.0.0/24"
    """CIDR for Metaflow VPC Subnet 1"""

    subnet_2_cidr: str = "10.20.1.0/24"
    """CIDR for Metaflow VPC Subnet 2"""

    max_vcpu_batch: conint(ge=16, le=256) = 64
    """Maximum VCPUs for Batch Compute Environment [16-256]. You can change the upper limit by editing the Cloudformation template"""

    min_vcpu_batch: Literal[0, 2, 4, 8, 16] = 8
    """Minimum VCPUs for Batch Compute Environment [0-16] for EC2 Batch Compute Environment (ignored for Fargate)"""

    desired_vcpu_batch: Literal[0, 2, 4, 8, 16] = 16
    """Desired Starting VCPUs for Batch Compute Environment [0-16] for EC2 Batch Compute Environment (ignored for Fargate)"""

    compute_env_instance_types: str = "c4.large,c4.xlarge,c4.2xlarge,c4.4xlarge,c4.8xlarge"
    """The instance types for the compute environment as a comma-separated list"""

    enable_custom_role: bool = False
    """CustomRole: Enable custom role with restricted permissions?"""

    enable_api_basic_auth: bool = True
    """APIBasicAuth: Enable basic auth for API Gateway? (requires you to export the API key from API Gateway console)"""

    enable_sagemaker: bool = True
    """Enable Sagemaker Notebooks"""

    batch_type: Literal["ec2", "fargate"] = "ec2"
    """AWS Batch compute type"""

    iam_partition: Literal["aws", "aws-us-gov"] = "aws"
    """IAM Partition (Select aws-us-gov for AWS GovCloud, otherwise leave as is)"""

    additional_worker_policy_arn: Optional[str] = None
    """Additional IAM Policy ARN to attach to Batch Compute Environment (leave empty, unless you know what you are doing)"""

    enable_ui: bool = False
    """Enable Metaflow UI. Make sure to specify PublicDomainName and CertificateArn if you do"""

    public_domain_name: Optional[str] = None
    """The custom domain name for UI (e.g., ui.outerbounds.co). Has to match the certificate. Required if UI is enabled"""

    certificate_arn: Optional[str] = None
    """
    The ARN of a ACM certificate valid for the custom domain name. Required if UI is enabled
    
    TODO: use a DNS Validated Cert to automate this; then deprecate this field
    """

    @property
    def enable_additional_worker_policy(self) -> bool:
        return bool(self.additional_worker_policy_arn)
