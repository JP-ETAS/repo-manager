import json
import subprocess
import tempfile

class Repo:
    def __init__(self, repo, common):
        self._common = common
        self._repo = repo
        self.name = self._get_field("name")
        self.fork_url = self._get_field("fork_url")
        self.secrets = self._get_list_field("secrets")
        self.variables = self._get_list_field("variables")
        self.permissions = self._get_list_field("permissions")
        self.org = self._get_field("org")

    def _get_field(self, field_name):
        """Gets a non-list field from a repo config, or from common if not found in repo config."""
        field_value = self._repo.get(field_name, self._common.get(field_name, None))
        if field_value is None:
            raise ValueError(f"No value found for field {field_name} and no default set")
        if type(field_value) is list:
            raise ValueError(f"Field {field_name} is a list, use _get_list_field instead")
        return field_value

    def _get_list_field(self, field_name):
        """
        Gets a list field from a repo config, or from common if not found in repo config.
        Allows a user to merge common and repo config with the syntax common.<field>
        """
        field_value_list = self._repo.get(field_name, None)
        field_value_list_common = self._common.get(field_name, None)
        if field_value_list is None:
            if field_value_list_common is None:
                raise ValueError(f"No value found for field list {field_name} and no default set")
            field_value_list = field_value_list_common
        elif f"common.{field_name}" in field_value_list:
            if field_value_list_common is None:
                raise ValueError(f"Field {field_name} requested to inherit from common but field doesn't exist in common")

            field_value_list.remove(f"common.{field_name}")
            field_value_list.extend(field_value_list_common)  

        if type(field_value_list) is not list:
            raise ValueError(f"Field {field_name} is not a list, use _get_field instead")
        return field_value_list

    def check_variables(self):
        existing_variables_json = subprocess.check_output(["gh", "api", f"repos/{self.org}/{self.name}/actions/variables"])
        existing_variables = json.loads(existing_variables_json.decode('utf-8'))
        vars_list = [{"key": var["name"], "value": var["value"]} for var in existing_variables.get("variables", [])]

        print(vars_list)

    def set_secrets_or_vars(self, set_secrets):
        if set_secrets:
            to_set = "secret"
            names_and_values = self.secrets
        else:
            to_set = "variable"
            names_and_values = self.variables

        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as temp_file:
            for secret_or_var in names_and_values:
                temp_file.write(f"{secret_or_var['name']}={secret_or_var['value']}")
            temp_file.flush()
            if subprocess.call(["gh", to_set, "set", "-f", temp_file.name, "--repo", f"{self.org}/{self.name}"]) != 0:
                raise ValueError(f"Failed to set {to_set} for repo {self.name}")

    def set_variables(self):
        self.set_secrets_or_vars(set_secrets=False)
        
    def set_secrets(self):
        self.set_secrets_or_vars(set_secrets=True)

    def set_permissions(self):
        for permission in self.permissions:
            team_slug = permission["team_slug"]
            permission = permission["permission"]   
            if subprocess.call([
                "gh", "api", 
                "-X", "PUT",
                f"/orgs/{self.org}/teams/{team_slug}/repos/{self.org}/{self.name}",
                "-f", f"permission={permission}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
                raise ValueError(f"Failed to set permission {permission} for team {team_slug} on repo {self.name}")

    def create(self):
        print(f"Creating repo {self.name} in org {self.org}")
        if subprocess.call(["gh", "repo", "fork", self.fork_url, "--clone=false", "--org", self.org, "--default-branch-only"]) != 0:
            raise ValueError(f"Failed to fork repo {self.fork_url} into org {self.org}")
        print(f"Setting permissions for repo {self.name}")
        self.set_permissions()
        print(f"Setting variables for repo {self.name}")
        self.set_variables()
        print(f"Setting secrets for repo {self.name}")
        self.set_secrets()

    def check_permissions(self):
        """Check current team permissions for the repository"""
        try:
            # Get team permissions
            teams_result = subprocess.run([
                "gh", "api", f"repos/{self.org}/{self.name}/teams"
            ], capture_output=True, text=True, check=True)
            
            teams_data = json.loads(teams_result.stdout)
            print(f"Current team permissions for {self.name}:")
            for team in teams_data:
                print(f"  Team: {team['name']} (slug: {team['slug']}) - Permission: {team['permission']}")
            
            return teams_data
            
        except subprocess.CalledProcessError as e:
            print(f"Failed to get permissions for repo {self.name}: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Failed to parse permissions response for repo {self.name}: {e}")
            return None

    def update(self):
        print(f"Updating repo {self.name} in org {self.org}")
        self.check_permissions()

    def exists(self):
        return subprocess.call(["gh", "api", f"repos/{self.org}/{self.name}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    def create_or_update(self):
        if self.exists():
            self.update()
        else:
            self.create()

with open("config.json", "r") as config_file:
    config = json.load(config_file)

for repo in config.get("repos", []):
    Repo(repo, config["common"]).create_or_update()