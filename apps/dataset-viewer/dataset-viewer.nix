{pkgs, ...}:
pkgs.python3Packages.buildPythonApplication {
  name = "dataset-viewer";
  src = ./dataset-viewer.py;
  dontUnpack = true;
  pyproject = false;

  nativeBuildInputs = with pkgs; [
    wrapGAppsHook4
    gobject-introspection
  ];

  buildInputs = with pkgs; [
    libadwaita
  ];

  preFixup = ''
    gappsWrapperArgs+=(--prefix PYTHONPATH : "${pkgs.python3.withPackages (p: [
      p.pygobject3
    ])}/${pkgs.python3.sitePackages}")
  '';

  buildPhase = ''
    install -m 755 -D $src $out/bin/ds
  '';

  meta.mainProgram = "ds";
}
