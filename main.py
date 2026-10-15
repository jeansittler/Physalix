"""Point d'entrée de Physalix en développement."""

if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "--distribution-check":
        from physalix._distribution_check import run
        raise SystemExit(run(sys.argv[2]))
    else:
        from physalix.startup import SingleInstance, show_startup_error

        instance = SingleInstance()
        try:
            if not instance.acquire():
                instance.activate_existing()
                raise SystemExit(0)
            from physalix.app import main
            raise SystemExit(main(instance))
        except SystemExit:
            raise
        except Exception as error:
            show_startup_error(error)
            raise SystemExit(1) from error
        finally:
            instance.close()
