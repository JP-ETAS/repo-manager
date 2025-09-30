import json
import subprocess
import tempfile
from enum import Enum

class Environment(Enum):
    SECRET = "secret"
    VARIABLE = "variable"

class Repo:
    def __init__(self, repo, common):
        self._common = common
        self._repo = repo
        self.name = self._get_field("name")
        self.fork_url = self._get_field("fork_url")
        self.secrets = self._get_field("secrets")
        self.variables = self._get_field("variables")
        self.permissions = self._get_field("permissions")
        self.org = self._get_field("org")
        self.hostname = self._get_field("hostname")

    def _get_field(self, field_name):
        """Gets a non-list field from a repo config, or from common if not found in repo config."""
        field_value = self._repo.get(field_name, self._common.get(field_name, None))
        if field_value is None:
            raise ValueError(f"No value found for field {field_name}")
        return field_value

    def check_variables(self):
        existing_variables_json = subprocess.check_output(["gh", "api", f"repos/{self.org}/{self.name}/actions/variables", "--hostname", self.hostname])
        existing_variables = json.loads(existing_variables_json.decode('utf-8'))
        vars_list = [{"key": var["name"], "value": var["value"]} for var in existing_variables.get("variables", [])]

        print(vars_list)
    
    def update_environment(self, environment: Environment):
        if environment == Environment.SECRET:
            environment_data = self.secrets
        else:
            environment_data = self.variables

        values_result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}/actions/{environment.value}s", "--hostname", self.hostname
        ], capture_output=True, text=True, check=True)
        existing_data = {value["name"]: value.get("value", "***") for value in json.loads(values_result.stdout).get(f"{environment.value}s", [])}

        all_data = set(existing_data.keys()).union(set(environment_data.keys()))

        overwritten = ""
        edited = ""
        added = ""
        removed = ""
        unchanged = ""
        for value_name in all_data:
            present_in_existing = value_name in existing_data
            present_in_config = value_name in environment_data
            if present_in_existing and present_in_config:
                if existing_data[value_name] == "***":
                    overwritten += f"    {value_name}: *** => ***\n"
                    self.add_environment(environment, value_name, environment_data[value_name])
                elif existing_data[value_name] != environment_data[value_name]:
                    edited += f"    {value_name}: {existing_data[value_name]} => {environment_data[value_name] if environment == Environment.VARIABLE else '***'}\n"
                    self.add_environment(environment, value_name, environment_data[value_name])
                else:
                    unchanged += f"    {value_name}: {existing_data[value_name]}\n"
            elif not present_in_existing and present_in_config:
                added += f"    {value_name}: {environment_data[value_name] if environment == Environment.VARIABLE else '***'}\n"
                self.add_environment(environment, value_name, environment_data[value_name])
            elif present_in_existing and not present_in_config:
                removed += f"    {value_name}: {existing_data[value_name]}\n"
                self.remove_environment_value(environment, value_name)

        print(f"{environment.value.capitalize()}s:")
        if overwritten:
            print(f"  Overwritten:\n{overwritten}", end="")
        if edited:
            print(f"  Edited:\n{edited}", end="")
        if added:
            print(f"  Added:\n{added}", end="")
        if removed:
            print(f"  Removed:\n{removed}", end="")
        if unchanged:
            print(f"  Unchanged:\n{unchanged}", end="")

    def remove_environment(self, environment: Environment, value_name):
        result = subprocess.run([
            "gh", "api", "-X", "DELETE", 
            f"repos/{self.org}/{self.name}/actions/{environment.value}s/{value_name}",
            "--hostname", self.hostname
        ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error deleting {environment.value}: {value_name}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to delete {environment.value} {value_name} from repo {self.name}")

    def add_environment(self, environment: Environment, key, value):
        result = subprocess.run([
            "gh", "api", "-X", "PUT",
            f"repos/{self.org}/{self.name}/actions/{environment.value}s/{key}",
            "-f", f"{environment.value}={value}",
            "--hostname", self.hostname
        ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error setting {environment.value} {key}:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to set {environment.value} {key} for repo {self.name}")

    def update_variables(self):
        self.update_environment(Environment.VARIABLE)

    def update_secrets(self):
        self.update_environment(Environment.SECRET)

    def set_variables(self):
        for key, value in self.variables.items():
            self.add_environment(Environment.VARIABLE, key, value)

    def set_secrets(self):
        for key, value in self.secrets.items():
            self.add_environment(Environment.SECRET, key, value)

    ###############
    # PERMISSIONS #
    ###############
    def set_permissions(self):
        for permission in self.permissions:
            team_slug = permission["slug"]
            permission = permission["permission"]   
            self.add_permission(team_slug, permission)    
            
    def add_permission(self, team_slug, permission):
        result = subprocess.run([
                "gh", "api", 
                "-X", "PUT",
                f"/orgs/{self.org}/teams/{team_slug}/repos/{self.org}/{self.name}",
                "-f", f"permission={permission}", "--hostname", self.hostname
            ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error setting permission for team {team_slug}:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to set permission {permission} for team {team_slug} on repo {self.name}")
    
    def remove_permission(self, team_slug):
        result = subprocess.run([
                "gh", "api", 
                "-X", "DELETE",
                f"/orgs/{self.org}/teams/{team_slug}/repos/{self.org}/{self.name}", "--hostname", self.hostname
            ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error removing permission for team {team_slug}:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to remove permissions for team {team_slug} on repo {self.name}")

    def update_permissions(self):
        """Check current team permissions for the repository"""
        # Get team permissions
        teams_result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}/teams", "--hostname", self.hostname
        ], capture_output=True, text=True, check=True)

        existing_perms = { perm["slug"]: perm["permission"] for perm in json.loads(teams_result.stdout) }

        all_teams = set(existing_perms.keys()).union(set(self.permissions.keys()))
        edited = ""
        added = ""
        removed = ""
        unchanged = ""
        for team in all_teams:
            present_in_existing = team in existing_perms
            present_in_config = team in self.permissions
            if present_in_existing and present_in_config:
                if existing_perms[team] != self.permissions[team]:
                    edited += f"    {team}: {existing_perms[team]} => {self.permissions[team]}\n"
                    self.add_permission(team, self.permissions[team])
                else:
                    unchanged += f"    {team}: {existing_perms[team]}\n"
            elif not present_in_existing and present_in_config:
                added += f"    {team}: {self.permissions[team]}\n"
                self.add_permission(team, self.permissions[team])
            elif present_in_existing and not present_in_config:
                removed += f"    {team}: {existing_perms[team]}\n"
                self.remove_permission(team)
        print("Permissions:")
        if edited:
            print(f"  Edited:\n{edited}", end="")
        if added:
            print(f"  Added:\n{added}", end="")
        if removed:
            print(f"  Removed:\n{removed}", end="")
        if unchanged:
            print(f"  Unchanged:\n{unchanged}", end="")

    def create(self):
        print(f"Creating repo {self.name} in org {self.org}")
        if subprocess.call(["gh", "repo", "fork", self.fork_url, "--clone=false", "--org", self.org, "--default-branch-only", "--hostname", self.hostname]) != 0:
            raise ValueError(f"Failed to fork repo {self.fork_url} into org {self.org}")
        print(f"Setting permissions for repo {self.name}")
        self.set_permissions()
        print(f"Setting variables for repo {self.name}")
        self.set_variables()
        #print(f"Setting secrets for repo {self.name}")
        #self.set_secrets()

    def update(self):
        print(f"Updating repo {self.name} in org {self.org}")
        print(f"Setting permissions for repo {self.name}")
        self.update_permissions()
        print(f"Setting variables for repo {self.name}")
        self.update_variables()
        #print(f"Setting secrets for repo {self.name}")
        #self.update_secrets()

    def exists(self):
        result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}", "--hostname", self.hostname
        ], capture_output=True, text=True)

        if result.returncode == 0:
            return True

        if "404" in result.stderr or "Not Found" in result.stderr:
            return False

        print(f"Error checking if repo {self.org}/{self.name} exists:")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        raise ValueError(f"Unable to determine if repo {self.org}/{self.name} exists due to error (exit code {result.returncode})")

    def create_or_update(self):
        if self.exists():
            self.update()
        else:
            self.create()

with open("config.json", "r") as config_file:
    config = json.load(config_file)

for repo in config.get("repos", []):
    Repo(repo, config["common"]).create_or_update()