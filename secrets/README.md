# Secrets

Production secrets are stored as sops-encrypted YAML files in this directory,
decrypted at container startup via `scripts/entrypoint.sh`.

## First-time setup

1. Generate an age keypair on your laptop:
   ```
   age-keygen -o ~/.donna/age.key
   cat ~/.donna/age.key | grep '# public key:'
   ```

2. Create `.sops.yaml` at repo root with the public key (already scaffolded):
   ```yaml
   creation_rules:
     - path_regex: secrets/.*\.enc\.yaml$
       age: age1abc...your-public-key-here
   ```

3. Create `secrets/prod.enc.yaml` (encrypted):
   ```bash
   cat > /tmp/plain.yaml <<'EOF'
   DISCORD_BOT_TOKEN=...
   ANTHROPIC_API_KEY=sk-ant-...
   TAVILY_API_KEY=tvly-...
   VOYAGE_API_KEY=pa-...
   DISCORD_ALLOWED_USER_ID=123456789012345678
   EOF
   sops -e /tmp/plain.yaml > secrets/prod.enc.yaml
   rm /tmp/plain.yaml
   ```

4. Copy the private key to the droplet (one-time):
   ```
   scp ~/.donna/age.key scout:/etc/bot/age.key
   ssh scout "sudo chmod 600 /etc/bot/age.key && sudo chown bot:bot /etc/bot/age.key"
   ```

## Rotation

Every 90 days:
 - Rotate each API key with its provider
 - Re-encrypt `prod.enc.yaml` with sops
 - Commit the new encrypted file, push, droplet picks up within 5 min
 - Leave the age key alone; only rotate age on a machine change

## What is NEVER committed

 - `age.key` (the private key)
 - Plain `.env.production` / `.env`
 - Anything not encrypted by sops

See `.gitignore`.
