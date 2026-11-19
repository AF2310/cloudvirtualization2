# 2DV705 — Cloud Infrastructure on AWS (lnu-notes)

This repository sets up the `lnu-notes` web app on AWS (`eu-north-1`) using Terraform and `cloud-init`.

## What It Builds
- **Network (VPC `10.0.0.0/16`):** One public subnet (`10.0.1.0/24`) with an Internet Gateway, and one private subnet (`10.0.2.0/24`) with a NAT Gateway.
- **Web Server (`t3.micro`, public subnet):** Runs the Python notes app on port `80`. SSH (port `22`) is only open to your own IP (`var.admin_cidr`). Uses an IAM role (`2dv705-web`) to talk to S3 instead of access keys.
- **Database Server (`t3.micro`, private subnet):** Runs MariaDB with no public IP and no SSH access. Port `3306` only accepts traffic from the web server's security group (`aws_security_group.web.id`).
- **S3 Bucket:** Stores uploaded images privately. Block Public Access, `AES256` encryption, and versioning are all turned on. Images are shown using 5-minute presigned URLs.

---

## How to Deploy from Scratch

### Before You Start
- Install AWS CLI v2 and sign in with `aws configure` (region: `eu-north-1`).
- Install Terraform `1.6` or newer.
- Make sure you have an EC2 key pair named `2dv705` in `eu-north-1` (or change `key_name` in `terraform.tfvars`):
  ```powershell
  aws ec2 create-key-pair --region eu-north-1 --key-name 2dv705 --query KeyMaterial --output text | Out-File -Encoding ascii "$HOME\.ssh\2dv705.pem"
  ```

### Build Everything
Run these commands from `lnu-notes\terraform` in PowerShell:

```powershell
cd lnu-notes\terraform
Copy-Item terraform.tfvars.example terraform.tfvars
```

Open `terraform.tfvars` and fill in your own public IP and the app repo URL:
```hcl
admin_cidr = "<YOUR_PUBLIC_IP>/32"
repo_url   = "https://github.com/naser-sadeghi/lnu-notes.git"
```

Then run Terraform:
```powershell
terraform init
terraform plan
terraform apply
```

Wait about 60–90 seconds for `cloud-init` to finish installing Python and MariaDB, then check `/healthz`:
```powershell
python ..\..\poll_health.py
```

---

## Testing & Reproducing the Report Results

Run all commands below from `lnu-notes\terraform` in PowerShell.

### 1. First Plan (Task 2)
```powershell
terraform init
terraform plan
```
**What you should see:** `Plan: 23 to add, 0 to change, 0 to destroy.`

### 2. App Health & Database Isolation (Task 10)
```powershell
curl.exe -s (terraform output -raw health_url)
```
**What you should see:**
```json
{"app":"ok","bucket":"2dv705-<ACCOUNT_ID>-notes","database":"ok","db_host":"10.0.2.x","region":"eu-north-1","s3":"ok"}
```

Check that your laptop cannot reach port `3306` on the database:
```powershell
Test-NetConnection -ComputerName (terraform output -raw db_private_ip) -Port 3306
```
**What you should see:** `PingSucceeded : False` and `TcpTestSucceeded : False`.

### 3. S3 Bucket Lock-Down & Access Denied Check (Tasks 11–12)
```powershell
$bucket = terraform output -raw bucket

# Check that Block Public Access and AES256 encryption are on
aws s3api get-public-access-block --region eu-north-1 --bucket $bucket
aws s3api get-bucket-encryption --region eu-north-1 --bucket $bucket --output text --query "ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault"

# Try uploading directly from your laptop (should be blocked)
aws s3 cp ..\requirements.txt "s3://$bucket/test.txt"

# Try opening an image URL without logging in (should return 403)
curl.exe -I "https://$bucket.s3.eu-north-1.amazonaws.com/notes/<OBJECT_KEY>"
```
**What you should see:**
- All 4 Block Public Access settings are `true`, and encryption is `AES256`.
- `aws s3 cp` fails with `AccessDenied` (`explicit deny in a resource-based policy`).
- `curl.exe -I` returns `HTTP/1.1 403 Forbidden`.

### 4. Configuration Drift Check (Task 13)
```powershell
$bucket = terraform output -raw bucket

# Turn off Block Public Access manually to simulate a console change
aws s3api put-public-access-block --region eu-north-1 --bucket $bucket --public-access-block-configuration BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false

# Let Terraform spot the change and fix it
terraform plan
terraform apply -auto-approve
```
**What you should see:**
- `terraform plan` shows all 4 settings changing `false -> true` (`Plan: 0 to add, 1 to change, 0 to destroy.`).
- `terraform apply` puts them back (`Apply complete! Resources: 0 added, 1 changed, 0 destroyed.`).

### 5. Destroy, Rebuild & Resize Test (Tasks 14–15)
```powershell
terraform destroy -auto-approve
terraform apply -auto-approve

# Preview changing both instances from t3.micro to t3.small
terraform plan -var="instance_type=t3.small"
```
**What you should see:**
- `destroy`: `Destroy complete! Resources: 23 destroyed.`
- `apply`: `Apply complete! Resources: 23 added, 0 changed, 0 destroyed.`
- `plan -var="instance_type=t3.small"`: `Plan: 0 to add, 2 to change, 0 to destroy.`

### 6. Check State File for Passwords (Task 16)
```powershell
(Select-String -Path terraform.tfstate -Pattern 'db_password' | Measure-Object).Count
```
**What you should see:** `2` before moving the password to SSM Parameter Store, and `0` after following `lnu-notes\terraform\README-changes.md`.

### 7. Full Teardown & Cleanup Check
```powershell
terraform destroy -auto-approve

aws ec2 describe-instances --region eu-north-1 --query "Reservations[].Instances[?State.Name!='terminated'].InstanceId" --output text
aws s3 ls
aws ec2 describe-volumes --region eu-north-1 --query "Volumes[?State=='available'].VolumeId" --output text
aws ec2 describe-nat-gateways --region eu-north-1 --query "NatGateways[?State!='deleted'].NatGatewayId" --output text
aws ec2 describe-vpcs --region eu-north-1 --query 'Vpcs[?IsDefault==`false`].VpcId' --output text
```
**What you should see:** `Destroy complete! Resources: 23 destroyed.` and empty output for all 5 AWS CLI checks (no leftover resources billing you).

### 8. Quick Recovery (Rebuild & Wait for Health Check)
```powershell
terraform apply -auto-approve
python ..\..\poll_health.py
```
**What you should see:** `Apply complete! Resources: 23 added, 0 changed, 0 destroyed.` and then `HEALTHZ READY: {"app":"ok",...,"database":"ok",...,"s3":"ok",...}` once `cloud-init` finishes.

---

## Appendix: Colleague Rebuild Notes (Task 17)

I was initially confused about which repository to clone (`naser-sadeghi/lnu-notes.git` vs my own `AF2310/cloudvirtualization2.git`) and wrote a Linux `sed -i` one-liner in the report. A few things to keep in mind:
1. **Two different repo roles:** You clone **`AF2310/cloudvirtualization2.git`** to get the Terraform files (`lnu-notes\terraform`), while `repo_url` inside `terraform.tfvars` still points to **`https://github.com/naser-sadeghi/lnu-notes.git`** because `cloud-init` clones `app.py` from the root of that repo.
2. **`sed -i` is Linux-only:** `sed -i "s|...|"` works on Linux, fails on macOS (needs `sed -i ''`), and does not exist in Windows PowerShell.
3. **Key pair prerequisite:** Terraform expects an EC2 key pair named `2dv705` to already exist in `eu-north-1`.

### Original Report Version (Linux `sed`, from the course repo)
```bash
git clone https://github.com/naser-sadeghi/lnu-notes.git && cd lnu-notes/terraform
cp terraform.tfvars.example terraform.tfvars
sed -i "s|{YOUR_IP}|$(curl -s https://checkip.amazonaws.com)|; s|{GITHUB_NAME}|naser-sadeghi|" terraform.tfvars
terraform init && terraform apply -auto-approve
```

### Alternative Rebuild Commands (From This Repo, No `sed` Needed)
Run in PowerShell on a machine with AWS CLI configured (`aws configure`):

```powershell
# 1. Clone this repository and move into the Terraform folder
git clone https://github.com/AF2310/cloudvirtualization2.git
cd cloudvirtualization2\lnu-notes\terraform

# 2. Create the 2dv705 key pair in eu-north-1 if it does not exist yet
aws ec2 describe-key-pairs --region eu-north-1 --key-names 2dv705 2>$null
if ($LASTEXITCODE -ne 0) {
  aws ec2 create-key-pair --region eu-north-1 --key-name 2dv705 --query KeyMaterial --output text | Out-File -Encoding ascii "$HOME\.ssh\2dv705.pem"
}

# 3. Write terraform.tfvars directly without sed
$myip = (curl.exe -s https://checkip.amazonaws.com).Trim()
@"
admin_cidr = "$myip/32"
repo_url   = "https://github.com/naser-sadeghi/lnu-notes.git"
"@ | Out-File -Encoding ascii terraform.tfvars

# 4. Initialize, deploy, and wait for /healthz
terraform init
terraform apply -auto-approve
python ..\..\poll_health.py
```
