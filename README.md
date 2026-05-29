# Legacy4 - AWS Elastic Beanstalk Deployment Guide

This repository contains a Docker Compose setup (Nginx frontend & Python backend) for AWS Elastic Beanstalk deployment.

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

## 🔄 Updating the Application (Manual Deploy)

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