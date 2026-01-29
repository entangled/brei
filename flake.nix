{
  description = "Minimal workflow system and alternative to Make";

  inputs.pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
  inputs.pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs =
  { nixpkgs, pyproject-nix, flake-utils, ... }: flake-utils.lib.eachDefaultSystem (system:
  let

    project = pyproject-nix.lib.project.loadPoetryPyproject {
      projectRoot = ./.;
    };

    pythonAttr = "python3";

    overlay = final: prev: {
      pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
        (python-final: python-prev: { 
          argh = python-prev.argh.overridePythonAttrs(old: rec {
            version = "0.30.5";
            src = python-final.fetchPypi {
              pname = "argh";
              inherit version;
              sha256 = "sha256-s339YXoJ0ZpKe8rtDgYLKIvHrI39wPrPiGpJol/zNyg=";
            };
            doCheck = false;
          });
          rich = python-prev.rich.overridePythonAttrs(old: rec {
            version = "13.8.1";
            src = final.fetchFromGitHub {
              owner = "Textualize";
              repo = "rich";
              rev = "refs/tags/v${version}";
              sha256 = "sha256-k+a64GDGzRDprvJz7s9Sm4z8jDV5TZ+CZLMgXKXXonM=";
            };
            doCheck = false;
          });
        })
      ];
    };
  in
  let
    pkgs = import nixpkgs { inherit system; overlays = [ overlay ]; };
    python = pkgs.${pythonAttr};
    pythonEnv = python.withPackages (project.renderers.withPackages { inherit python; });
  in
  {
    devShells.default = pkgs.mkShell { packages = [ pythonEnv ]; };
    packages.default = python.pkgs.buildPythonPackage (project.renderers.buildPythonPackage { inherit python; });
  });
}
