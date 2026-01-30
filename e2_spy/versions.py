import json
import pathlib
from typing import TypedDict


class PackageJsonDict(TypedDict):
    dependencies: dict[str, str]


package_json = pathlib.Path("package.json")
with package_json.open() as f:
    data: PackageJsonDict = json.load(f)

bi: str = data["dependencies"]["bootstrap-icons"]
bs: str = data["dependencies"]["bootstrap"]
hx: str = data["dependencies"]["htmx.org"]
