import re

class Mutator:
    @staticmethod
    def mutate(path: str) -> set[str]:
        mutations = set()
        
        # 1. Version mutation (v1 -> v2, v1.0 -> v1.1)
        if "v" in path:
            # v1 -> v2
            try:
                mutations.add(re.sub(r"v(\d+)", lambda m: f"v{int(m.group(1)) + 1}", path))
                mutations.add(re.sub(r"v(\d+)", lambda m: f"v{max(0, int(m.group(1)) - 1)}", path))
            except Exception:
                pass
        
        # 2. Number mutation (user1 -> user2)
        try:
            mutations.add(re.sub(r"(\d+)", lambda m: str(int(m.group(1)) + 1), path))
            mutations.add(re.sub(r"(\d+)", lambda m: str(max(0, int(m.group(1)) - 1)), path))
        except Exception:
            pass
        
        # 3. Common backup extensions
        mutations.add(path + ".bak")
        mutations.add(path + ".old")
        mutations.add(path + "~")
        mutations.add(path + ".swp")
        mutations.add(path + ".tmp")
        
        if "." in path:
            # Swap extension
            try:
                base, ext = path.rsplit(".", 1)
                if ext == "php":
                    mutations.add(f"{base}.phps")
                    mutations.add(f"{base}.php.bak")
                    mutations.add(f"{base}.php.old")
                elif ext == "jsp":
                    mutations.add(f"{base}.jsp.bak")
                    mutations.add(f"{base}.jspx")
                elif ext == "asp":
                    mutations.add(f"{base}.aspx")
                elif ext == "aspx":
                    mutations.add(f"{base}.asp")
            except ValueError:
                pass
        
        # 4. Environment/Debug
        if not path.endswith("/"):
            mutations.add(path + "/debug")
            mutations.add(path + "/test")
            mutations.add(path + "/admin")
        
        return {m for m in mutations if m != path}
