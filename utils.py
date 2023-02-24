def get_repo_ref(config, tree_name):
    for tree in config["trees"]:
        if tree["name"] == tree_name:
            return tree["git_repo"], tree["git_ref"]
    raise RuntimeError(f"Could not find git repo and ref for {tree_name}?")
