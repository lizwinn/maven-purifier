# SPDX-License-Identifier: MIT
{ ... }:
{
  config,
  inputs,
  lib,
  ...
}:
{

  imports = [ inputs.flake-parts.flakeModules.partitions ];

  debug = false;
  caisson = {
    libOverlays.exported = libOverlays: {
      inherit (libOverlays) default;
    };

    # The scope `pkgs.maven-purifier` comes from the `default` entry of the
    # package overlay registry (pkg-overlays/): the package set applies it
    # by default, and the flake exports it as `pkgOverlays` and as the plain
    # `overlays.default`. The scope holds the builder, a function, so the
    # flake exports its derivations by name below rather than every
    # attribute of the scope.
    nixpkgs = {
      packages.export.enabled = false;
    };
  };

  # `nix run github:nix-purifiers/maven-purifier -- lock` locks the build in
  # the current directory, and `… -- mvn <args>` runs Maven offline from
  # the lock.
  perSystem =
    { pkgs, ... }:
    {
      packages = {
        inherit (pkgs.maven-purifier) cli extension;
        default = pkgs.maven-purifier.cli;
      };
    };

  partitionedAttrs.checks = "checks";
  partitionedAttrs.formatter = "formatter";

  partitions.formatter = {
    extraInputs = (lib.caisson.pins.flake-compat ../../../tests/dependencies).sources;
    module =
      { inputs, ... }:
      {
        imports = [ inputs.treefmt-nix.flakeModule ];
        perSystem.treefmt.programs.nixfmt.enable = true;
      };
  };

  partitions.checks = {
    extraInputs = (lib.caisson.pins.flake-compat ../../../tests/dependencies).sources;
    module =
      { inputs, self, ... }:
      {
        imports = [ inputs.treefmt-nix.flakeModule ];
        perSystem =
          { pkgs, system, ... }:
          {
            checks = import ../../../tests {
              inherit pkgs;
              overlay = self.overlays.default;
              inherit (self.packages.${system}) cli extension;
            };
            treefmt.programs.nixfmt.enable = true;
          };
      };
  };

}
