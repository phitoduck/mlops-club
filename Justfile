# install the project's python packages and other useful
install: require-venv
    # install useful VS Code extensions
    which code && code --install-extension njpwerner.autodocstring
    # install python packages not belonging to any particular package in this repo,
    # but important for
    python -m pip install \
        pre-commit \
        phitoduck-projen \
        black \
        pylint \
        flake8 \
        mypy
    # install the metaflow-deployment package as an "editable" package
    python -m pip install -e ./metaflow-deployment[all]
    # install pre-commit hooks to protect the quality of code committed by contributors
    pre-commit install
    # install git lfs for downloading rootski CSVs and other large files in the repo
    git lfs install

# certain boilerplate files like setup.cfg, setup.py, and .gitignore are "locked";
# you can modify their contents by editing the .projenrc.py file in the root of the repo.
update-boilerplate-files: require-venv
    python .projenrc.py

# throw an error if a virtual environment isn't activated;
# add this as a requirement to other targets that you want to ensure always run in
# some kind of activated virtual environment
require-venv:
    #!/usr/bin/env python
    import sys
    from textwrap import dedent

    def get_base_prefix_compat():
        """Get base/real prefix, or sys.prefix if there is none."""
        return getattr(sys, "base_prefix", None) or getattr(sys, "real_prefix", None) or sys.prefix

    def in_virtualenv():
        return get_base_prefix_compat() != sys.prefix

    if not in_virtualenv():
        print(dedent("""\
            ⛔️ ERROR: 'just' detected that you have not activated a python virtual environment.

            Science has shown that installing python packages (e.g. 'pip install pandas')
            without a virtual environment increases likelihood of getting ulcers and COVID. 🧪👩‍🔬

            To resolve this error, please activate a virtual environment by running
            whichever of the following commands apply to you:

            ```bash
            # create a (virtual) copy of the python just for this project
            python -m venv ./venv/

            # activate that copy of python (now 'which python' points to your new virtual copy)
            source ./venv/bin/activate

            # re-run whatever 'just' command you just tried to run, for example
            just install
            ```

            -- Sincerely, The venv police 👮 🐍
        """))

        sys.exit(1)
