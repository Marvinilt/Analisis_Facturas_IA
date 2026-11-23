"""Las pruebas nunca usan la carpeta data/ real: se fija una carpeta temporal antes de importar la app."""
import os
import tempfile

os.environ["FACTURAS_IA_DATA"] = tempfile.mkdtemp(prefix="facturas_ia_pruebas_")
