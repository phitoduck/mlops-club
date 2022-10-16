# AWS CDK Library for Metaflow

AWS CDK is AWS's modern tool for infrastructure as code. It's *soooo* much better than writing CloudFormation YAML.

Currently, there is no up-to-date CDK library for deploying Metaflow. 

We are trying to satisfy both the hobbyist's and the small-to-medium enterprise's Metaflow needs.

For this reason, we are creating a CDK library around Metaflow so that users can opt into
features that make sense for them. For example, an enterprise may want a dedicated VPC
for Metaflow to run in, whereas a hobbyist may prefer to use the default VPC because it is free.

These kinds of decisions should be supported here via parameters and useful "CDK Constructs".
Constructs are compositions of one or more AWS resources configured to solve a particular problem.
For example an `S3StaticSite` construct may create an S3 bucket, an `index.html` file inside, and
a CloudFront distribution to serve the site to the world.