import subprocess
import sys
import time
import urllib.request

# Use CLI argument if provided; otherwise read the current IP dynamically from Terraform state.
url = (
    sys.argv[1]
    if len(sys.argv) > 1
    else subprocess.check_output(["terraform", "output", "-raw", "health_url"], text=True).strip()
)
print(f"Polling {url} ...")

# Retry up to 30 times (~2.5 min) while cloud-init installs packages and MariaDB boots.
for i in range(30):
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = resp.read().decode('utf-8')
            if 'database":"ok"' in data:
                print('HEALTHZ READY:', data)
                break  # Both web and database tiers are up.
            else:
                print(f'Attempt {i+1}: DB not ready yet: {data}')
    except Exception:
        # Connection refused / timeout means Apache or Python app is still starting via cloud-init.
        print(f'Attempt {i+1}: waiting for cloud-init...')
    time.sleep(5)
