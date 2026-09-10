"""Point d'entrée de Physalix en développement."""

if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "--distribution-check":
        from physalix._distribution_check import run
        raise SystemExit(run(sys.argv[2]))
    else:
        from physalix.app import main
        raise SystemExit(main())
