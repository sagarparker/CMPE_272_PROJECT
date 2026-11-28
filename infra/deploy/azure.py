#!/usr/bin/env python3
"""Repeatable Azure VM provisioning and Compose deployment. Uses az, ssh and public HTTPS Git."""
import argparse
import ipaddress
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'infra/deploy/runtime/azure-state.json'
REMOTE = '/opt/mediamesh'


def run(args, capture=False, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, **kwargs).stdout


def az(*args):
    return json.loads(run(['az', *args, '--output', 'json', '--only-show-errors'], capture=True) or 'null')


def read_env(path):
    """Read dotenv data without sourcing it or expanding shell commands/variables."""
    values = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, raw = line.partition('=')
        key = key.strip()
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError(f'Invalid .env assignment at line {number}')
        lexer = shlex.shlex(raw, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = '#'
        try:
            parts = list(lexer)
        except ValueError:
            raise ValueError(f'Invalid .env quoting at line {number}') from None
        if len(parts) > 1:
            raise ValueError(f'Quote values containing spaces at .env line {number}')
        values[key] = parts[0] if parts else ''
    return values


CONFIG_KEYS = {
    'subscription': 'AZURE_SUBSCRIPTION', 'resource_group': 'AZURE_RESOURCE_GROUP',
    'location': 'AZURE_LOCATION', 'vm_name': 'AZURE_VM_NAME', 'dns_label': 'AZURE_DNS_LABEL',
    'storage_account': 'AZURE_STORAGE_ACCOUNT', 'container': 'AZURE_STORAGE_CONTAINER',
    'admin_email': 'ADMIN_EMAIL', 'certificate_email': 'ACME_EMAIL',
    'ssh_cidr': 'AZURE_SSH_CIDR', 'ssh_key': 'AZURE_SSH_KEY',
    'ssh_user': 'AZURE_SSH_USER', 'vm_size': 'AZURE_VM_SIZE',
}


def load_config(path):
    values = read_env(path)
    c = {key: values[variable] for key, variable in CONFIG_KEYS.items() if values.get(variable)}
    for key, default in {'location': 'swedencentral', 'ssh_key': '~/.ssh/mediamesh',
                         'ssh_user': 'azureuser', 'vm_size': 'Standard_B2as_v2', 'container': 'mediamesh'}.items():
        c.setdefault(key, default)
    required = ['subscription', 'resource_group', 'location', 'vm_name', 'dns_label',
                'storage_account', 'admin_email', 'certificate_email', 'ssh_cidr', 'ssh_key']
    for key in required:
        if not c.get(key):
            raise ValueError(f'Missing deployment env setting: {CONFIG_KEYS[key]}')
    for key in ['resource_group', 'vm_name', 'dns_label', 'storage_account']:
        if not re.fullmatch(r'[a-z][a-z0-9-]{2,62}', c[key]):
            raise ValueError(f'Invalid {CONFIG_KEYS[key]}')
    if not re.fullmatch(r'[a-z0-9]{3,24}', c['storage_account']):
        raise ValueError('Storage account must be 3–24 lowercase letters/digits')
    network = ipaddress.ip_network(c['ssh_cidr'], strict=False)
    if network.version != 4 or network.prefixlen != 32:
        raise ValueError('AZURE_SSH_CIDR must be your public IPv4 address followed by /32')
    c['ssh_key'] = str(Path(c['ssh_key']).expanduser().resolve())
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', c['ssh_user']):
        raise ValueError('Invalid SSH username')
    return c


def deployment_credentials(path):
    values = read_env(path)
    credentials = {}
    for name in ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'ML_OPENROUTER_API_KEY']:
        value = values.get(name, '')
        if not value or any(ch in value for ch in "\n\r'\\"):
            raise ValueError(f'{name} must be set in the deployment env file, on one line without single quotes or backslashes')
        credentials[name] = value
    return credentials


def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.write_text(json.dumps(s, indent=2) + '\n')
    STATE.chmod(0o600)


def state(c):
    s = json.loads(STATE.read_text())
    if any(s[k] != c[k] for k in ['subscription', 'resource_group', 'vm_name']):
        raise ValueError('Saved state belongs to another deployment; use its matching config')
    return s


def ssh(s, command, **kwargs):
    return run(['ssh', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15',
                '-i', s['ssh_key'], f"{s['ssh_user']}@{s['host']}", command], **kwargs)


def published_release():
    if run(['git', 'status', '--porcelain', '--untracked-files=normal'], capture=True, cwd=ROOT).strip():
        raise ValueError('Commit intended source changes first. Only the committed release is deployed.')
    branch = run(['git', 'branch', '--show-current'], capture=True, cwd=ROOT).strip()
    if branch != 'main':
        raise ValueError('Deploy from main: git switch main, then git pull --ff-only origin main.')
    repository = run(['git', 'remote', 'get-url', 'origin'], capture=True, cwd=ROOT).strip()
    repository = re.sub(r'^git@github.com:', 'https://github.com/', repository)
    if not re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('origin must point to a public GitHub repository without embedded credentials')
    revision = run(['git', 'rev-parse', 'HEAD'], capture=True, cwd=ROOT).strip()
    # Check publication anonymously against the same HTTPS repository the VM uses.
    refs = run(['git', '-c', 'credential.helper=', 'ls-remote', repository, 'refs/heads/main'], capture=True, cwd=ROOT)
    if revision not in [line.split()[0] for line in refs.splitlines()]:
        raise ValueError('Local main must match published origin/main. Push your main commit or pull --ff-only origin main before deploying.')
    return repository, revision


def checkout_release(s, repository, revision):
    mirror = f'{REMOTE}/repository.git'
    release = f'{REMOTE}/releases/{revision}'
    ssh(s, 'set -eu; export GIT_TERMINAL_PROMPT=0; '
        f'mkdir -p {REMOTE}/releases {REMOTE}/shared; chmod 700 {REMOTE}/shared; '
        f'if [ ! -d {mirror} ]; then git -c credential.helper= clone --mirror '
        f'{shlex.quote(repository)} {mirror}; fi; '
        f'git --git-dir={mirror} remote set-url origin {shlex.quote(repository)}; '
        f'git -c credential.helper= --git-dir={mirror} fetch --prune origin; '
        f'if [ ! -d {release} ]; then git --git-dir={mirror} worktree add --detach '
        f'{release} {revision}; fi; '
        f'test "$(git -C {release} rev-parse HEAD)" = {shlex.quote(revision)}')


def provision(c):
    # An explicit subscription is passed on every resource command. Never touch the old VM.
    subscription = az('account', 'show', '--subscription', c['subscription'])['id']
    c['subscription'] = subscription
    scope = ['--subscription', subscription]
    if not Path(c['ssh_key']).is_file() or not Path(c['ssh_key'] + '.pub').is_file():
        raise ValueError('Generate the dedicated SSH key and .pub file first (see guide)')
    exists = az('group', 'exists', '--name', c['resource_group'], *scope)
    if exists and not STATE.exists():
        raise ValueError('Resource group already exists without local state. Choose a NEW group; existing deployments are protected.')
    if STATE.exists():
        state(c)
    az('group', 'create', '--name', c['resource_group'], '--location', c['location'],
       '--tags', 'project=mediamesh-script', *scope)
    # Save progress so provisioning can be retried after quota/IAM/network failures.
    save_state(c)
    common = ['--resource-group', c['resource_group'], *scope]
    az('network', 'nsg', 'create', '--name', 'mediamesh-nsg', *common)
    for priority, name, port, source in [(100, 'SSH', '22', c['ssh_cidr']),
                                         (110, 'HTTP', '80', '*'), (120, 'HTTPS', '443', '*')]:
        az('network', 'nsg', 'rule', 'create', '--nsg-name', 'mediamesh-nsg',
           '--name', name, '--priority', str(priority), '--access', 'Allow',
           '--protocol', 'Tcp', '--direction', 'Inbound', '--source-address-prefixes', source,
           '--destination-port-ranges', port, *common)
    vms = az('vm', 'list', *common)
    if not any(v['name'] == c['vm_name'] for v in vms):
        az('vm', 'create', '--name', c['vm_name'], '--image', 'Ubuntu2404',
           '--size', c['vm_size'], '--admin-username', c['ssh_user'],
           '--ssh-key-values', Path(c['ssh_key'] + '.pub').read_text().strip(),
           '--assign-identity', '--nsg', 'mediamesh-nsg', '--public-ip-sku', 'Standard',
           '--public-ip-address-allocation', 'Static', '--public-ip-address-dns-name', c['dns_label'],
           '--storage-sku', 'StandardSSD_LRS', '--os-disk-size-gb', '100', *common)
    vm = az('vm', 'show', '--name', c['vm_name'], '--show-details', *common)
    c.update(host=vm['publicIps'], domain=vm['fqdns'])
    if not c['domain']:
        raise ValueError('VM has no DNS hostname; inspect its public IP DNS settings')
    save_state(c)
    az('storage', 'account', 'create', '--name', c['storage_account'], '--sku', 'Standard_LRS',
       '--kind', 'StorageV2', '--https-only', 'true', '--min-tls-version', 'TLS1_2',
       '--allow-blob-public-access', 'false', '--allow-shared-key-access', 'false', *common)
    account = az('storage', 'account', 'show', '--name', c['storage_account'], *common)
    # Management-plane container creation requires no storage keys or operator data role.
    az('storage', 'container-rm', 'create', '--storage-account', c['storage_account'],
       '--name', c['container'], '--public-access', 'off', *common)
    container_scope = account['id'] + '/blobServices/default/containers/' + c['container']
    for role, role_scope in [('Storage Blob Data Contributor', container_scope),
                             ('Storage Blob Delegator', account['id'])]:
        existing = az('role', 'assignment', 'list', '--scope', role_scope, *scope)
        if not any(r['principalId'] == vm['identity']['principalId'] and r['roleDefinitionName'] == role for r in existing):
            az('role', 'assignment', 'create', '--assignee-object-id', vm['identity']['principalId'],
               '--assignee-principal-type', 'ServicePrincipal', '--role', role, '--scope', role_scope, *scope)
    # Set CORS through ARM; no account keys or operator Blob data permissions needed.
    url = 'https://management.azure.com' + account['id'] + '/blobServices/default?api-version=2023-05-01'
    properties = az('rest', '--method', 'get', '--url', url)['properties']
    properties['cors'] = {'corsRules': [{'allowedOrigins': ['https://' + c['domain']],
        'allowedMethods': ['GET', 'HEAD', 'PUT', 'OPTIONS'],
        'allowedHeaders': ['content-type', 'if-none-match', 'x-ms-blob-type', 'x-ms-version', 'range'],
        'exposedHeaders': ['ETag'], 'maxAgeInSeconds': 300}]}
    properties['deleteRetentionPolicy'] = {'enabled': True, 'days': 7}
    properties['isVersioningEnabled'] = True
    az('rest', '--method', 'put', '--url', url, '--body', json.dumps({'properties': properties}))
    c['provisioned'] = True
    save_state(c)
    print(f"Provisioned https://{c['domain']}. Google OAuth redirect URI:\n"
          f"https://{c['domain']}/auth/realms/mediamesh/broker/google/endpoint")
    print('Next: configure Google OAuth, then run the deploy command.')


def deploy(s, credentials, source=None):
    repository, revision = source or published_release()
    release = f'{REMOTE}/releases/{revision}'
    ssh(s, 'sudo mkdir -p /opt/mediamesh && sudo chown "$(id -un):$(id -gn)" /opt/mediamesh')
    bootstrap = '''set -eu
if ! command -v git >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y git
fi
if ! sudo docker compose version >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl python3
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\\n' "$(dpkg --print-architecture)" "$VERSION_CODENAME" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo systemctl enable --now docker
'''
    ssh(s, 'sh -s', input=bootstrap)
    checkout_release(s, repository, revision)
    prepare = ['python3', 'infra/deploy/prepare.py', '--domain', s['domain'], '--email', s['certificate_email'],
               '--admin-email', s['admin_email'], '--account', s['storage_account'], '--container', s['container']]
    ssh(s, f'cd {release} && if [ ! -d {REMOTE}/shared/runtime ]; then {shlex.join(prepare)} && '
           f'mv infra/deploy/runtime {REMOTE}/shared/runtime; fi && '
           f'ln -sfn {REMOTE}/shared/runtime infra/deploy/runtime')
    # stdin to SSH, never command arguments, logs, Git, or shell history.
    update = """import pathlib, os
os.umask(0o077)
p = pathlib.Path('/opt/mediamesh/shared/runtime/deploy.env')
values = dict(line.split('=', 1) for line in p.read_text().splitlines() if '=' in line)
values.update(CREDENTIALS)
p.write_text(''.join(k + '=' + v + '\\n' for k, v in values.items()))
p.chmod(0o600)
""".replace('CREDENTIALS', repr({k: "'" + v + "'" for k, v in credentials.items()}))
    ssh(s, 'python3 -', input=update)
    # Back up existing databases before builds or Flyway migrations.
    ssh(s, f'if [ -L {REMOTE}/current ]; then cd {REMOTE}/current; '
           f'sudo ./infra/deploy/backup.sh; fi')
    ssh(s, f'cd {release} && sudo ./infra/deploy/compose.sh config --quiet && '
           'sudo ./infra/deploy/compose.sh --parallel 1 build && '
           'sudo ./infra/deploy/compose.sh up -d --wait --wait-timeout 1200')
    ssh(s, f'ln -sfn {release} {REMOTE}/current && cd {release} && sudo ./infra/deploy/compose.sh ps')
    print(f'Deployed {revision} to https://{s["domain"]}. Test Google login, upload, search and playback.')


def ensure_ssh_key(c):
    key = Path(c['ssh_key'])
    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        run(['ssh-keygen', '-t', 'ed25519', '-f', key])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file', default=str(ROOT / '.env.deploy'), help='Local dotenv file (default: project .env.deploy)')
    p.add_argument('action', choices=['auto', 'provision', 'deploy', 'status', 'restart', 'stop', 'vm-stop', 'vm-start'])
    p.add_argument('services', nargs='*')
    args = p.parse_args()
    source = published_release() if args.action == 'auto' else None
    c = load_config(args.env_file)
    credentials = deployment_credentials(args.env_file) if args.action in ['auto', 'deploy'] else None
    if args.action == 'auto':
        try:
            run(['az', 'account', 'show', '--output', 'none'], capture=True)
        except subprocess.CalledProcessError:
            run(['az', 'login', '--output', 'none'])
    # Resolve name/GUID consistently, without switching the user's default subscription.
    c['subscription'] = az('account', 'show', '--subscription', c['subscription'])['id']
    if args.services and args.action != 'restart':
        p.error('Service names are supported only for restart')
    allowed = {'edge', 'frontend', 'backend', 'postgres', 'keycloak', 'ml-api', 'ml-worker', 'prometheus'}
    if set(args.services) - allowed:
        p.error('Unknown service name')
    if args.action == 'auto':
        ensure_ssh_key(c)
        if not STATE.exists() or not json.loads(STATE.read_text()).get('provisioned'):
            provision(c)
        s = state(c)
        print('Google OAuth redirect URI: ' + f'https://{s["domain"]}/auth/realms/mediamesh/broker/google/endpoint')
        deploy(s, credentials, source)
        return
    if args.action == 'provision':
        ensure_ssh_key(c)
        provision(c)
        return
    s = state(c)
    if args.action == 'deploy':
        deploy(s, credentials)
    elif args.action in ['vm-stop', 'vm-start']:
        az('vm', 'deallocate' if args.action == 'vm-stop' else 'start', '--subscription', s['subscription'],
           '--resource-group', s['resource_group'], '--name', s['vm_name'])
    else:
        command = {'status': 'ps --all', 'stop': 'stop', 'restart': 'restart'}[args.action]
        ssh(s, f'cd {REMOTE}/current && sudo ./infra/deploy/compose.sh {command} ' + shlex.join(args.services))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # Never echo subprocess command arguments: they may carry configuration.
        print(f'Failed: {exc}' if not isinstance(exc, subprocess.CalledProcessError)
              else f'Command failed (exit {exc.returncode}). See the tool error above; fix it and rerun.', file=sys.stderr)
        sys.exit(1)
