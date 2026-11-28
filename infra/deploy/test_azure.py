"""Local guard/dispatch tests; no Azure resources or SSH connections."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('azure_deploy', Path(__file__).with_name('azure.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DeploymentGuards(unittest.TestCase):
    def config(self, folder):
        values = {'AZURE_SUBSCRIPTION': 'student', 'AZURE_RESOURCE_GROUP': 'rg-test',
                  'AZURE_VM_NAME': 'vm-test', 'AZURE_DNS_LABEL': 'mediamesh-test',
                  'AZURE_STORAGE_ACCOUNT': 'mediameshtest', 'ADMIN_EMAIL': 'a@example.com',
                  'ACME_EMAIL': 'a@example.com'}
        path = Path(folder) / '.env'
        path.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
        return path, values

    def test_config_does_not_require_ip_restriction(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.config(folder)
            self.assertNotIn('ssh_cidr', module.load_config(path))

    def test_provision_opens_ssh_and_requires_key_authentication(self):
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder) / 'key'
            key.touch()
            Path(str(key) + '.pub').write_text('ssh-ed25519 test-key')
            def azure(*args):
                if args[:2] == ('account', 'show'):
                    return {'id': 'subscription'}
                if args[:2] == ('group', 'exists'):
                    return False
                if args[:2] == ('vm', 'list'):
                    return []
                if args[:2] == ('vm', 'create'):
                    raise RuntimeError('stop before resource creation')
            config = dict(subscription='subscription', ssh_key=str(key), resource_group='rg-test',
                          location='swedencentral', vm_name='vm-test', vm_size='Standard_B2as_v2',
                          ssh_user='azureuser', dns_label='mediamesh-test')
            with patch.object(module, 'STATE', Path(folder) / 'state.json'), patch.object(module, 'az', side_effect=azure) as calls:
                with self.assertRaisesRegex(RuntimeError, 'stop before'):
                    module.provision(config)
            rule = next(c.args for c in calls.call_args_list if c.args[:4] == ('network', 'nsg', 'rule', 'create') and 'SSH' in c.args)
            self.assertEqual(rule[rule.index('--source-address-prefixes') + 1], '*')
            create = calls.call_args.args
            self.assertEqual(create[create.index('--authentication-type') + 1], 'ssh')
            self.assertIn('--ssh-key-values', create)

    def test_mismatched_vm_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            path.write_text(json.dumps(dict(subscription='sub', resource_group='old', vm_name='old')))
            with patch.object(module, 'STATE', path):
                with self.assertRaisesRegex(ValueError, 'another deployment'):
                    module.state(dict(subscription='sub', resource_group='new', vm_name='new'))

    def test_existing_group_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder) / 'key'
            key.touch()
            Path(str(key) + '.pub').touch()
            with patch.object(module, 'STATE', Path(folder) / 'absent.json'), patch.object(module, 'az') as azure:
                azure.side_effect = [{'id': 'sub'}, True]
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    module.provision(dict(subscription='sub', ssh_key=str(key), resource_group='existing'))
                self.assertEqual(azure.call_count, 2)
                self.assertFalse(any('create' in call.args for call in azure.call_args_list))

    def test_dirty_source_does_not_connect(self):
        with patch.object(module, 'run', return_value=' M source.py'), patch.object(module, 'ssh') as ssh:
            with self.assertRaisesRegex(ValueError, 'Commit intended'):
                module.deploy({}, {})
            ssh.assert_not_called()

    def test_unpushed_commit_is_rejected(self):
        with patch.object(module, 'run', side_effect=['', 'main', 'https://github.com/example/public.git', 'a' * 40, 'b' * 40 + '\trefs/heads/main\n']):
            with self.assertRaisesRegex(ValueError, 'Local main must match'):
                module.published_release()

    def test_feature_branch_cannot_deploy(self):
        with patch.object(module, 'run', side_effect=['', 'feature/example']):
            with self.assertRaisesRegex(ValueError, 'Deploy from main'):
                module.published_release()

    def test_feature_branch_tip_does_not_count_as_main(self):
        revision = 'a' * 40
        with patch.object(module, 'run', side_effect=['', 'main', 'https://github.com/example/public.git', revision, 'b' * 40 + '\trefs/heads/main\n']) as command:
            with self.assertRaisesRegex(ValueError, 'Local main must match'):
                module.published_release()
            self.assertEqual(command.call_args.args[0][-1], 'refs/heads/main')

    def test_public_origin_needs_no_credentials(self):
        revision = 'a' * 40
        with patch.object(module, 'run', side_effect=['', 'main', 'git@github.com:example/public.git', revision, revision + '\trefs/heads/main\n']):
            self.assertEqual(module.published_release(), ('https://github.com/example/public.git', revision))

    def test_git_checkout_fetches_updates_and_preserves_old_release(self):
        with tempfile.TemporaryDirectory() as folder:
            repository = Path(folder) / 'source'
            repository.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repository), *args], text=True, stderr=subprocess.DEVNULL).strip()
            git('init')
            git('config', 'user.email', 'test@example.com')
            git('config', 'user.name', 'Test')
            source = repository / 'version.txt'
            source.write_text('first')
            git('add', '.')
            git('commit', '-m', 'first')
            first = git('rev-parse', 'HEAD')
            remote = str(Path(folder) / 'vm')
            def local_ssh(state, command):
                subprocess.run(['sh', '-c', command], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with patch.object(module, 'REMOTE', remote), patch.object(module, 'ssh', side_effect=local_ssh):
                module.checkout_release({}, str(repository), first)
                # Retry the same release, then fetch a newer commit.
                module.checkout_release({}, str(repository), first)
                source.write_text('second')
                git('commit', '-am', 'second')
                second = git('rev-parse', 'HEAD')
                module.checkout_release({}, str(repository), second)
            self.assertEqual((Path(remote) / 'releases' / first / 'version.txt').read_text(), 'first')
            self.assertEqual((Path(remote) / 'releases' / second / 'version.txt').read_text(), 'second')

    def test_env_is_data_and_preserves_literal_dollars(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env'
            path.write_text("export NAME='Azure for Students' # comment\nKEY='$(touch NEVER_RUN)$TOKEN'\nEMPTY=\n")
            self.assertEqual(module.read_env(path), {'NAME': 'Azure for Students',
                             'KEY': '$(touch NEVER_RUN)$TOKEN', 'EMPTY': ''})

    def test_config_excludes_application_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.config(folder)
            with path.open('a') as stream:
                stream.write('GOOGLE_CLIENT_SECRET=private-value\n')
            self.assertNotIn('private-value', json.dumps(module.load_config(path)))

    def test_missing_secret_fails_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env'
            path.write_text('GOOGLE_CLIENT_ID=private-value\n')
            with self.assertRaisesRegex(ValueError, '^GOOGLE_CLIENT_SECRET must be set'):
                module.deployment_credentials(path)

    def test_credentials_use_stdin_and_preserve_generated_passwords(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / 'deploy.env'
            env.write_text('DATABASE_PASSWORD=generated-password\nGOOGLE_CLIENT_SECRET=old\n')
            credentials = {'GOOGLE_CLIENT_ID': 'client', 'GOOGLE_CLIENT_SECRET': '$literal-secret',
                           'ML_OPENROUTER_API_KEY': 'router-key'}
            calls = []
            def remote(state, command, **kwargs):
                calls.append(command)
                if command == 'python3 -':
                    script = kwargs['input'].replace('/opt/mediamesh/shared/runtime/deploy.env', str(env))
                    exec(compile(script, '<credential-update>', 'exec'), {})
            state = dict(domain='test.example.org', certificate_email='a@example.com',
                         admin_email='a@example.com', storage_account='teststorage', container='mediamesh')
            with patch.object(module, 'ssh', side_effect=remote), patch.object(module, 'checkout_release'):
                module.deploy(state, credentials, ('https://github.com/example/public.git', 'a' * 40))
            self.assertEqual(module.read_env(env)['DATABASE_PASSWORD'], 'generated-password')
            self.assertEqual(module.read_env(env)['GOOGLE_CLIENT_SECRET'], '$literal-secret')
            self.assertEqual(module.read_env(env)['ADMIN_EMAIL'], 'a@example.com')
            self.assertFalse(any('$literal-secret' in command for command in calls))
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)

    def test_deployment_defaults_are_separate_from_app_env(self):
        launcher = (module.ROOT / 'deploy').read_text()
        self.assertIn('${DEPLOY_ENV_FILE:-.env.deploy}', launcher)
        with patch('sys.argv', ['azure.py', 'status']), patch.object(module, 'load_config', side_effect=ValueError('stop')) as load:
            with self.assertRaisesRegex(ValueError, 'stop'):
                module.main()
            self.assertEqual(load.call_args.args[0], str(module.ROOT / '.env.deploy'))

    def test_current_admin_email_overrides_saved_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            saved = dict(subscription='sub', resource_group='rg', vm_name='vm',
                         admin_email='old@example.com', domain='host.example.com')
            path.write_text(json.dumps(saved))
            current = dict(saved, admin_email='new@example.com', certificate_email='a@example.com',
                           ssh_key='/key', ssh_user='azureuser')
            with patch.object(module, 'STATE', path):
                self.assertEqual(module.state(current)['admin_email'], 'new@example.com')

    def test_invalid_email_is_rejected_before_provisioning(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.config(folder)
            with path.open('a') as stream:
                stream.write('ADMIN_EMAIL=not-an-email\n')
            with self.assertRaisesRegex(ValueError, 'Invalid ADMIN_EMAIL'):
                module.load_config(path)

    def test_storage_changes_are_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            saved = dict(subscription='sub', resource_group='rg', vm_name='vm', storage_account='oldstorage')
            path.write_text(json.dumps(saved))
            with patch.object(module, 'STATE', path):
                with self.assertRaisesRegex(ValueError, 'AZURE_STORAGE_ACCOUNT differs'):
                    module.state(dict(saved, storage_account='newstorage'))

    def test_missing_state_has_recovery_message(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(module, 'STATE', Path(folder) / 'missing.json'):
                with self.assertRaisesRegex(ValueError, 'No saved deployment state'):
                    module.state({})

    def test_google_change_stays_pending_until_updater_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / 'deploy.env'
            env.write_text('DATABASE_PASSWORD=preserved\nGOOGLE_CLIENT_ID=old\nGOOGLE_CLIENT_SECRET=old\n')
            config = dict(admin_email='new@example.com', certificate_email='a@example.com')
            credentials = dict(GOOGLE_CLIENT_ID='new', GOOGLE_CLIENT_SECRET='new-secret', ML_OPENROUTER_API_KEY='key')
            def execute(state, command, **kwargs):
                script = kwargs['input'].replace('/opt/mediamesh/shared/runtime/deploy.env', str(env))
                exec(compile(script, '<sync>', 'exec'), {})
            with patch.object(module, 'ssh', side_effect=execute):
                module.sync_runtime(config, credentials)
                self.assertTrue(env.with_name('google-update-pending').exists())
                env.with_name('google-update-pending').unlink()
                module.sync_runtime(config, credentials)
                self.assertFalse(env.with_name('google-update-pending').exists())
            self.assertEqual(module.read_env(env)['DATABASE_PASSWORD'], 'preserved')
            self.assertFalse(env.with_suffix('.env.tmp').exists())

    def test_ssh_transient_failure_retries_but_bad_key_does_not(self):
        config = dict(ssh_key='/key', ssh_user='azureuser', host='192.0.2.1')
        failed = subprocess.CompletedProcess([], 255, stderr='Connection refused')
        ready = subprocess.CompletedProcess([], 0, stderr='')
        with patch.object(module.subprocess, 'run', side_effect=[failed, ready]), patch.object(module.time, 'sleep') as sleep:
            module.wait_for_ssh(config)
            sleep.assert_called_once_with(5)
        with patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255, stderr='Permission denied (publickey)')), patch.object(module.time, 'sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'ssh-add'):
                module.wait_for_ssh(config)
            sleep.assert_not_called()

    def test_configure_does_not_build_or_fetch_source(self):
        with patch('sys.argv', ['azure.py', 'configure']), patch.object(module, 'load_config', return_value={'subscription': 'sub'}), patch.object(module, 'deployment_credentials', return_value={}), patch.object(module, 'az', return_value={'id': 'sub'}), patch.object(module, 'state', return_value={}), patch.object(module, 'sync_runtime') as sync, patch.object(module, 'sync_google'), patch.object(module, 'published_release') as source, patch.object(module, 'ssh') as ssh:
            module.main()
            sync.assert_called_once()
            source.assert_not_called()
            self.assertIn('--no-build', ssh.call_args.args[1])

    def test_clean_requires_explicit_flag_without_connecting(self):
        with patch.object(module, 'ssh') as ssh:
            with self.assertRaisesRegex(ValueError, 'clean --yes'):
                module.clean({})
            ssh.assert_not_called()

    def test_repeating_completed_clean_is_a_noop(self):
        with patch.object(module, 'ssh', return_value='no\n') as ssh:
            module.clean({}, confirmed=True)
            self.assertEqual(ssh.call_count, 1)

    def test_clean_is_scoped_and_stops_writers_before_deletion(self):
        release = module.REMOTE + '/releases/' + 'a' * 40
        with patch.object(module, 'ssh', side_effect=['yes\n', release + '\n', None, None, None]) as ssh:
            module.clean({}, confirmed=True)
        commands = [call.args[1] for call in ssh.call_args_list]
        self.assertTrue(commands[2].endswith('compose.sh stop'))
        self.assertIn('--no-deps --entrypoint python ml-worker', commands[3])
        self.assertIn('mediamesh-deploy_postgres-data', commands[4])
        self.assertNotIn('down -v', commands[4])
        self.assertNotIn('group delete', ' '.join(commands))
        self.assertIn("name_starts_with='assets/'", ssh.call_args_list[3].kwargs['input'])

    def test_state_is_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            with patch.object(module, 'STATE', path):
                module.save_state({'host': '192.0.2.1'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
