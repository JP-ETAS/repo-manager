import json
import subprocess
import tempfile

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

    def _get_field(self, field_name):
        """Gets a non-list field from a repo config, or from common if not found in repo config."""
        field_value = self._repo.get(field_name, self._common.get(field_name, None))
        if field_value is None:
            raise ValueError(f"No value found for field {field_name}")
        return field_value

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
            for key in names_and_values:
                temp_file.write(f"{key}={names_and_values[key]}\n")
            temp_file.flush()
            if subprocess.call(["gh", to_set, "set", "-f", temp_file.name, "--repo", f"{self.org}/{self.name}"]) != 0:
                raise ValueError(f"Failed to set {to_set} for repo {self.name}")

    def set_variables(self):
        self.set_secrets_or_vars(set_secrets=False)
        
    def set_secrets(self):
        self.set_secrets_or_vars(set_secrets=True)

    def set_permissions(self):
        for permission in self.permissions:
            team_slug = permission["slug"]
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

    def compare_permissions(self):
        """Check current team permissions for the repository"""
        # Get team permissions
        teams_result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}/teams"
        ], capture_output=True, text=True, check=True)

        existing_perms = { perm["slug"]: perm["permission"] for perm in json.loads(teams_result.stdout) }

        all_teams = set(existing_perms.keys()).union(set(self.permissions.keys()))
        print(all_teams)


    def update(self):
        print(f"Updating repo {self.name} in org {self.org}")
        self.compare_permissions()

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