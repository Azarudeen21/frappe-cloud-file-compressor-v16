from setuptools import find_packages, setup

setup(
    name="file_compressor",
    version="1.1.0",
    description="Automatic attachment compression for ERPNext/Frappe v16 on Frappe Cloud",
    packages=find_packages(),
    include_package_data=True,
    install_requires=["Pillow>=10.0.0"],
)
