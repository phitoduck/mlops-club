"""
Script that generates read-only boilerplate files.

Files that are managed with this project-scaffolding script
are read-only. They must not be changed manually! Instead,
modify this script and regenerate them.

Some files managed by this script are:
- .gitignore
- setup.cfg
- setup.py
- pyproject.toml
- MANIFEST.in

If you're confused/curious about why we use this file to manage other files,
you can learn about the tool here: https://github.com/phitoduck/phito-projen
"""

import json

from phito_projen import PythonPackage
from phito_projen.components.templatized_file import TemplatizedFile
from projen import Project

repo = Project(name="mlops-club")

metaflow_deployment_package = PythonPackage(
    parent=repo,
    version="0.0.0",
    name="metaflow-deployment",
    module_name="metaflow_iac",
)

sample_vscode_settings_json = TemplatizedFile(
    project=repo,
    file_path=".vscode/settings.json",
    make_comment_fn=lambda line: f"// {line}",
    supports_comments=True,
    template_body=json.dumps(
        {
            "restructuredtext.confPath": "",
            "autoDocstring.customTemplatePath": "./.vscode/rootski-python-docstring-template.mustache",
            "python.linting.pylintEnabled": True,
            "python.linting.pylintArgs": ["--rcfile=./linting/.pylintrc"],
            "python.formatting.provider": "black",
            "python.formatting.blackArgs": ["--line-length=112"],
            "python.linting.flake8Enabled": True,
            "python.linting.flake8Args": ["--config==./linting/.flake8", "--max-line-length=112"],
        },
        indent=4,
    ),
    is_sample=True,
)

repo.gitignore.add_patterns("venv", "*cache*", ".env")

# generate/update boilerplate project files in this repository
repo.synth()
