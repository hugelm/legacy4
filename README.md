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
eb create legacy4-env
```

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