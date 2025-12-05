# Vespa-app

A hybrid search application for deals/options with text, semantic, and geographic search capabilities.

## Features

- **Hybrid Search**: Combines BM25 text search, semantic search (E5 embeddings), and geographic search
- **Location-Aware**: Finds deals near user's location using GPS coordinates
- **Custom Ranking**: Multi-factor scoring including discounts, ratings, and distance
- **Vespa Cloud Ready**: Configured for cloud deployment with CI/CD pipeline

## Architecture

- **Container**: Handles search requests with custom `NearestLocationSearcher`
- **Content**: Stores and indexes deal/option documents
- **Schema**: `option.sd` defines document structure with embeddings and location data
- **Bundle**: Custom Java searcher for nearest location calculations

## Setup

### Prerequisites
1. Install Vespa CLI following this [guide](https://docs.vespa.ai/en/vespa-cli.html)
2. Set Vespa to target cloud: `vespa config set target cloud`

### Manual Deployment
```bash
vespa auth login
vespa config set application groupon.hybridsearch.default
vespa deploy
```

## CI/CD Pipeline

This project includes a comprehensive GitHub Actions CI/CD pipeline with four workflows:

### 🔄 **CI Workflow** (`.github/workflows/ci.yml`)
- **Triggers**: Push to `main`/`develop`, Pull Requests
- **Actions**:
  - Java 17 setup and Maven dependency caching
  - Vespa CLI installation and configuration validation
  - Maven build and JAR packaging
  - Application structure validation
  - Build artifact upload

### 🚀 **CD Workflow** (`.github/workflows/cd.yml`)
- **Triggers**: Push to `main`, Manual dispatch
- **Actions**:
  - Vespa Cloud authentication
  - Pre-deployment validation
  - Application deployment with health checks
  - Post-deployment verification
  - Environment-specific deployments (test/staging/prod)

### 🔄 **Promotion Workflow** (`.github/workflows/promote.yml`)
- **Triggers**: Manual dispatch only
- **Actions**:
  - Safe promotion between environments (test → staging → prod)
  - Confirmation requirement for safety
  - Pre-promotion validation
  - Post-promotion health checks

### ✅ **Validation Workflow** (`.github/workflows/validate.yml`)
- **Triggers**: Changes to configuration files
- **Actions**:
  - Services, deployment, and schema validation
  - Bundle structure verification
  - Configuration consistency checks
  - Schema field validation

### Required GitHub Secrets

Configure these secrets in your GitHub repository settings:

- `VESPA_CLI_API_KEY`: API key for Vespa Cloud control plane access (automatically consumed by Vespa CLI)
- `VESPA_APPLICATION_ID`: Your application ID (`groupon.hybridsearch.default`)

### Environment Configuration

The application supports three environments, each with separate application instances in Vespa Cloud:

- **Test**: `groupon.hybridsearch.default-test` - For development and testing
- **Staging**: `groupon.hybridsearch.default-staging` - For pre-production validation (lives in production)
- **Production**: `groupon.hybridsearch.default` - For live traffic

All environments use the same configuration (same `services.xml`, `schemas/`, etc.) but with different application IDs for complete isolation. Note that staging lives in production, so deployments use `vespa prod deploy` command.

#### Setting Up Staging Environment

To create a stable staging environment, you need to create a separate application instance in Vespa Cloud:

1. **Create the staging application instance** in Vespa Cloud console:
   - Application ID: `groupon.hybridsearch.default-staging`
   - Use the same configuration as production (same `services.xml`, `schemas/`, etc.)

2. **Deploy to staging** using the CD workflow:
   - The workflow automatically switches to the staging application ID before deploying
   - Command: `vespa config set application groupon.hybridsearch.default-staging`

3. **Benefits of separate instances**:
   - Complete isolation from production
   - Independent scaling and configuration
   - Safe testing without affecting production
   - Can run different versions simultaneously

The `deployment.xml` file in this repository is used for all instances, but each application instance manages its own deployment state independently.

### Pipeline Features

- **Automated Testing**: Prevents broken deployments
- **Configuration Validation**: Ensures Vespa configs are valid
- **Health Checks**: Post-deployment verification
- **Environment Management**: Support for test/staging/prod environments
- **Safe Promotion**: Controlled promotion between environments
- **Security**: Encrypted secrets and least privilege access
- **Rollback Support**: Easy rollback on deployment failures

### Deployment Workflow

1. **Development**: Push to `main` triggers automatic deployment to **test** environment
2. **Promotion**: Use manual promotion workflow to move from test → staging → prod
3. **Safety**: Each promotion requires confirmation and runs health checks
4. **Isolation**: Each environment has its own application ID for complete isolation

## Development

### Local Development
```bash
# Build the bundle
cd bundle
mvn clean package

# Copy JAR to components
cp target/nearest-location-1.0.0.jar ../components/

# Validate configuration
vespa config validate services.xml
vespa config validate deployment.xml
vespa config validate schemas/option.sd
```

### Project Structure
```
vespa-app/
├── .github/workflows/     # CI/CD pipeline
├── bundle/                # Java searcher bundle
├── components/            # Compiled JAR files
├── schemas/               # Vespa schema definitions
├── security/              # Security certificates
├── services.xml           # Vespa services configuration
├── deployment.xml         # Deployment configuration
└── README.md             # This file
```

## Configuration

### Application ID
The application is configured for: `groupon.hybridsearch.default`

### Key Components
- **Custom Searcher**: `NearestLocationSearcher` for location-based ranking
- **Embedding Model**: E5-small-v2 for semantic search
- **Schema**: `option.sd` with 384-dimensional embeddings
- **Ranking**: Complex multi-factor scoring function

## Monitoring

The CI/CD pipeline includes comprehensive monitoring:
- Build status reporting
- Deployment success/failure notifications
- Health check validation
- Configuration consistency verification
