#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { NetworkingStack } from '../lib/networking-stack';
import { DatabaseStack } from '../lib/database-stack';
import { CacheStack } from '../lib/cache-stack';
import { StorageStack } from '../lib/storage-stack';
import { ComputeStack } from '../lib/compute-stack';
import { ServicesStack } from '../lib/services-stack';
import { BatchStack } from '../lib/batch-stack';
import { AlbStack } from '../lib/alb-stack';
import { DeploymentStack } from '../lib/deployment-stack';
import { SecretsStack } from '../lib/secrets-stack';
import { WafStack } from '../lib/waf-stack';
import { LoggingStack } from '../lib/logging-stack';

const app = new cdk.App();

const env = app.node.tryGetContext('env') ?? 'dev';

const awsEnv = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
};

const commonTags = {
  Project: 'Zerna',
  Environment: env,
  ManagedBy: 'CDK',
};

const networking = new NetworkingStack(app, `Zerna-Networking-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna VPC and networking infrastructure (${env})`,
  tags: commonTags,
});

const database = new DatabaseStack(app, `Zerna-Database-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna RDS PostgreSQL database (${env})`,
  tags: commonTags,
  vpc: networking.vpc,
  rdsSg: networking.rdsSg,
});

const cache = new CacheStack(app, `Zerna-Cache-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna ElastiCache Redis cluster (${env})`,
  tags: commonTags,
  vpc: networking.vpc,
  redisSg: networking.redisSg,
});

const storage = new StorageStack(app, `Zerna-Storage-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna S3 storage buckets (${env})`,
  tags: commonTags,
});

const secrets = new SecretsStack(app, `Zerna-Secrets-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna secrets management and rotation (${env})`,
  tags: commonTags,
  vpc: networking.vpc,
  dbSecret: database.secret,
  dbInstance: database.cluster,
  redisAuthTokenSecret: cache.authTokenSecret,
  rdsSg: networking.rdsSg,
});

const compute = new ComputeStack(app, `Zerna-Compute-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna ECS compute cluster (${env})`,
  tags: commonTags,
  vpc: networking.vpc,
  datasetsBucket: storage.datasetsBucket,
  artifactsBucket: storage.artifactsBucket,
  dbSecret: database.secret,
  redisAuthTokenSecret: cache.authTokenSecret,
  apiKeySecrets: [
    secrets.jwtSigningKeySecret,
    secrets.openaiApiKeySecret,
    secrets.anthropicApiKeySecret,
  ],
});

const alb = new AlbStack(app, `Zerna-ALB-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna Application Load Balancer (${env})`,
  tags: commonTags,
  vpc: networking.vpc,
  albSg: networking.albSg,
});

const services = new ServicesStack(app, `Zerna-Services-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna ECS service task definitions (${env})`,
  tags: commonTags,
  cluster: compute.cluster,
  taskExecutionRole: compute.taskExecutionRole,
  taskRole: compute.taskRole,
  logGroup: compute.logGroup,
  dbSecret: database.secret,
  redisAuthTokenSecret: cache.authTokenSecret,
});

new BatchStack(app, `Zerna-Batch-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna AWS Batch compute workers (${env})`,
  tags: commonTags,
  vpc: networking.vpc,
  taskExecutionRole: compute.taskExecutionRole,
  taskRole: compute.taskRole,
  logGroup: compute.logGroup,
  datasetsBucket: storage.datasetsBucket,
  artifactsBucket: storage.artifactsBucket,
});

new WafStack(app, `Zerna-WAF-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna WAF and DDoS protection (${env})`,
  tags: commonTags,
  albArn: alb.alb.loadBalancerArn,
});

new DeploymentStack(app, `Zerna-Deployment-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna ECS Fargate service deployments (${env})`,
  tags: commonTags,
  vpc: networking.vpc,
  cluster: compute.cluster,
  webTaskDef: services.webTaskDef,
  apiTaskDef: services.apiTaskDef,
  temporalTaskDef: services.temporalTaskDef,
  workerTaskDef: services.workerTaskDef,
  webTargetGroup: alb.webTargetGroup,
  apiTargetGroup: alb.apiTargetGroup,
  webSg: networking.webSg,
  apiSg: networking.apiSg,
  temporalSg: networking.temporalSg,
});

new LoggingStack(app, `Zerna-Logging-${env}`, {
  env: awsEnv,
  environment: env,
  description: `Zerna log aggregation, metric filters, and alerts (${env})`,
  tags: commonTags,
});
