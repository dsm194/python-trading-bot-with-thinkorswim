#!/bin/bash

# 🔐 Replace with your actual VM public IP or load from .env
VM_IP=141.148.170.53
REMOTE_USER="ubuntu"
REMOTE_PATH="~/python-trading-bot-with-thinkorswim"
LOCAL_PATH=~/Documents/Trading/python/python-trading-bot-with-thinkorswim/

echo "📡 Syncing bot to $REMOTE_USER@$VM_IP..."

rsync -avz \
  --exclude '.venv' \
  --exclude '.git' \
  --exclude 'logs' \
  "$LOCAL_PATH" \
  "$REMOTE_USER@$VM_IP:$REMOTE_PATH"

echo "✅ Sync complete."

