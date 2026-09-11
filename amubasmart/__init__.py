"""AmubaSMART — frontend GUI+CLI SMART analyzer (terjemahan disk-health.sh).

SATU SUMBER VERSI. Semua build script (RPM/.deb/Inno) membaca angka dari sini,
jadi menaikkan versi cukup mengubah baris di bawah — tidak perlu edit banyak file.

Konvensi SemVer (MAYOR.MINOR.PATCH):
  PATCH  : perbaikan bug, tanpa fitur baru      (0.1.0 -> 0.1.1)
  MINOR  : fitur baru, tetap kompatibel          (0.1.x -> 0.2.0)
  MAYOR  : rilis matang / perubahan tak kompatibel (0.x -> 1.0.0)
"""
__version__ = "0.2.0"
