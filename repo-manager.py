import json
import subprocess
import tempfile
from enum import Enum

class Environment(Enum):
    SECRET = "secret"
    VARIABLE = "variable"

class Repo:
    """Class representing a repository to be managed."""

    def __init__(self, repo, common):
        """Initializes a Repo instance with configuration data.

        Reads fields from the repo config, falling back to common config if not present.
        """
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
    
    def update_environment(self, environment: Environment):
        """Updates secrets or variables for the repository.

        Compares existing secrets/variables with those in the config and adds/edits/removes as necessary.
        Secret values are not retrievable from GitHub, so if a secret exists in both config and repo it is always updated.
        """
        if environment == Environment.SECRET:
            environment_data = self.secrets
        else:
            environment_data = self.variables

        values_result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}/actions/{environment.value}s"
        ], capture_output=True, text=True, check=True)
        existing_data = {value["name"]: value.get("value", "***") for value in json.loads(values_result.stdout).get(f"{environment.value}s", [])}

        all_data = set(existing_data.keys()).union(set(environment_data.keys()))
        
        to_add={}
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
                    to_add[value_name] = environment_data[value_name]
                elif existing_data[value_name] != environment_data[value_name]:
                    edited += f"    {value_name}: {existing_data[value_name]} => {environment_data[value_name] if environment == Environment.VARIABLE else '***'}\n"
                    to_add[value_name] = environment_data[value_name]
                else:
                    unchanged += f"    {value_name}: {existing_data[value_name]}\n"
            elif not present_in_existing and present_in_config:
                added += f"    {value_name}: {environment_data[value_name] if environment == Environment.VARIABLE else '***'}\n"
                to_add[value_name] = environment_data[value_name]
            elif present_in_existing and not present_in_config:
                removed += f"    {value_name}: {existing_data[value_name]}\n"
                self.remove_environment_value(environment, value_name)

        if to_add:
            self.add_environment_values(environment, to_add)

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

    def remove_environment_value(self, environment: Environment, value_name):
        """Removes a secret or variable from the repository.
        
        TODO: Move to use gh CLI command instead of API.
        """
        result = subprocess.run([
            "gh", "api", "-X", "DELETE", 
            f"repos/{self.org}/{self.name}/actions/{environment.value}s/{value_name}"
        ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error deleting {environment.value}: {value_name}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to delete {environment.value} {value_name} from repo {self.name}")

    def add_environment_values(self, environment: Environment, values):
        """Adds secrets or variables to the repository in bulk.

        Writes all key-value pairs to a temporary file that is then passed to the gh CLI.
        """
        if not values:
            return
        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as temp_file:
            for key, value in values.items():
                temp_file.write(f"{key}={value}\n")
            temp_file.flush()
            
            result = subprocess.run([
                "gh", environment.value, "set", 
                "--repo", f"{self.org}/{self.name}",
                "-f", temp_file.name
            ], capture_output=True, text=True)
            
        if result.returncode != 0:
            print(f"Error setting {environment.value}:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to set {environment.value} for repo {self.name}")

    def update_variables(self):
        """Wrapper for environment update for variables."""
        self.update_environment(Environment.VARIABLE)

    def update_secrets(self):
        """Wrapper for environment update for secrets."""
        self.update_environment(Environment.SECRET)

    def set_variables(self):
        """Wrapper for add environment values for variables."""
        self.add_environment_values(Environment.VARIABLE, self.variables)

    def set_secrets(self):
        """Wrapper for add environment values for secrets."""
        self.add_environment_values(Environment.SECRET, self.secrets)


    def lock_main_branch(self):
        """Locks the main branch of the repository.
        
        Uses GH API through the GH CLI as there is no GH CLI command for this.
        """
        result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}/branches/main/protection",
            "--method", "PUT",
            "--field", "enforce_admins=true",
            "--field", "required_pull_request_reviews=null",
            "--field", "required_status_checks=null",
            "--field", "restrictions=null",
            "--field", "lock_branch=true",
            "--field", "allow_fork_syncing=true"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Error locking main branch for repo {self.name}:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to lock main branch for repo {self.name}")

    def set_permissions(self):
        """Sets team permissions for the repository."""
        for team_slug, permission in self.permissions.items():
            self.add_permission(team_slug, permission)

    def add_permission(self, team_slug, permission):
        """Adds a permission for a team on the repository.
        
        Uses GH API through the GH CLI as there is no GH CLI command for this.
        """
        result = subprocess.run([
                "gh", "api", 
                "-X", "PUT",
                f"/orgs/{self.org}/teams/{team_slug}/repos/{self.org}/{self.name}",
                "-f", f"permission={permission}"
            ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error setting permission for team {team_slug}:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to set permission {permission} for team {team_slug} on repo {self.name}")
    
    def remove_permission(self, team_slug):
        """Removes a team's permission on the repository.
        
        Uses GH API through the GH CLI as there is no GH CLI command for this.
        """
        result = subprocess.run([
                "gh", "api", 
                "-X", "DELETE",
                f"/orgs/{self.org}/teams/{team_slug}/repos/{self.org}/{self.name}"
            ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error removing permission for team {team_slug}:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise ValueError(f"Failed to remove permissions for team {team_slug} on repo {self.name}")

    def update_permissions(self):
        """Updates current team permissions for the repository.

        Compares existing permissions with those in the config and adds/edits/removes as necessary.
        """
        # Get team permissions
        teams_result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}/teams"
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
        """Creates a new repository and configures it."""
        print(f"Creating repo {self.name} in org {self.org}")
        # Re-add when testing in an org
        # if subprocess.call(["gh", "repo", "fork", self.fork_url, "--clone=false", "--org", self.org, "--default-branch-only"]) != 0:
        if subprocess.call(["gh", "repo", "fork", self.fork_url, "--clone=false", "--default-branch-only"]) != 0:
            raise ValueError(f"Failed to fork repo {self.fork_url} into org {self.org}")
        print(f"Setting permissions for repo {self.name}")
        self.set_permissions()
        print(f"Setting variables for repo {self.name}")
        self.set_variables()
        print(f"Setting secrets for repo {self.name}")
        self.set_secrets()
        print(f"Locking main branch for repo {self.name}")
        self.lock_main_branch()

    def update(self):
        """Updates an existing repository's configuration."""
        print(f"Updating repo {self.name} in org {self.org}")
        if subprocess.call(["gh", "repo", "sync", f"{self.org}/{self.name}"]) != 0:
            raise ValueError(f"Failed to sync repo {self.name} in org {self.org}")
        print(f"Setting permissions for repo {self.name}")
        self.update_permissions()
        print(f"Setting variables for repo {self.name}")
        self.update_variables()
        print(f"Setting secrets for repo {self.name}")
        self.update_secrets()
        print(f"Locking main branch for repo {self.name}")
        self.lock_main_branch()

    def exists(self):
        """Checks if the repository exists in the organization."""
        result = subprocess.run([
            "gh", "api", f"repos/{self.org}/{self.name}"
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
        """Creates or updates the repository based on its existence."""
        if self.exists():
            self.update()
        else:
            self.create()

if __name__ == "__main__":
    with open("config.json", "r") as config_file:
        config = json.load(config_file)

    for repo in config.get("repos", []):
        Repo(repo, config["common"]).create_or_update()
