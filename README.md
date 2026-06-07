# Legacy4 - AWS Elastic Beanstalk Deployment Guide

This repository contains a Docker Compose setup (Nginx frontend, Python backend & MariaDB database) for AWS Elastic Beanstalk deployment.

---

## 🚀 Initial Setup & Creation

Follow these steps to deploy the application for the first time using the **AWS CloudShell**.

### 1. Clone Repository
```bash
git clone https://github.com/hugelm/legacy4.git
cd legacy4
```

### 2. Initialize Elastic Beanstalk
```bash
eb init legacy4-app --platform "Docker running on 64bit Amazon Linux 2023" --region eu-central-1
```

### 3. Create the Environment
```bash
eb create legacy4-env \
  --envvars DB_ROOT_PASSWORD=your_root_password,DB_USER=your_db_user,DB_PASSWORD=your_db_password,DB_NAME=legacyhub
```

> ⚠️ Replace all database environment variables with secure credentials!

---

## 🔄 Updating the Application (Manual Deployment)

Whenever you push new changes to GitHub, pull them into your CloudShell environment to update the live application.

### 1. Pull Latest Changes
```bash
git remote add origin https://github.com/hugelm/legacy4.git
git pull origin main
```

### 2. Deploy Update
```bash
eb deploy legacy4-env
```

---

## 🤖 Automated Deployment via GitHub Actions

Once the environment is created, you can automate deployments. Every time you push code updates to GitHub, the pipeline will automatically package and deploy the new version.

### 1. Configure GitHub Repository Secrets
To grant GitHub permission to deploy to your AWS account, navigate to GitHub Repository → **Settings** → **Secrets and variables** → **Actions** and click **New repository secret**.

Add the following secrets:
* `AWS_ACCESS_KEY_ID`: Your AWS Access Key ID from IAM / Security credentials.
* `AWS_SECRET_ACCESS_KEY`: Your AWS Secret Access Key from IAM / Security credentials.

### 2. Triggering the Automation
Commit and push your changes to the `main` branch. The pipeline `.github/workflows/deploy.yml` will automatically build the `deploy.zip` and send it to AWS Elastic Beanstalk for deployment.
> **Info:** You can monitor the live building process under the **Actions** tab of the GitHub repository.

---

## 🔐 Environment Variables

All database credentials are managed via environment variables.

| Variable | Description |
|---|---|
| `DB_NAME` | Database name (default: `legacyhub`) |
| `DB_ROOT_PASSWORD` | MariaDB root password |
| `DB_USER` | Application DB user |
| `DB_PASSWORD` | Application DB password |

To view current secrets (environment variables), use `eb printenv`:
```bash
eb printenv
```

To change a secret (environment variable), use `eb setenv`:
```bash
eb setenv DB_PASSWORD=your_new_password
```
Elastic Beanstalk will restart the environment automatically to apply the new value.

> **Info:** MariaDB/Docker database images only initialize passwords and users once during the first creation of the database. If you change secrets later, the existing database inside the active Docker volume will ignore the new values. To force a new secret configuration, you must either create a fresh Elastic Beanstalk environment or increment the volume name in your `docker-compose.yml` (e.g. from `legacy4-db-data` to `legacy4-db-data-v2`). Note: Because `eb deploy` only pushes changes that are tracked by Git, you must run `git add` and `git commit` after changing the volume name locally, otherwise Elastic Beanstalk will deploy your old configuration.
---

## 📊 Monitoring & Debugging

Use these standard commands to check the health and performance of your containers.

### Check Environment Status
```bash
eb status
```

### View Live Container Logs
```bash
eb logs
```