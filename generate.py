from rr_license import LicenseGenerator

print("=" * 50)
print("  RR BILLING PRO — Generator Kode Lisensi")
print("=" * 50)

print("\nPilih Edition:")
print("1. BULANAN  (31 hari)")
print("2. 3BULAN   (92 hari)")
print("3. TAHUNAN  (365 hari)")
print("4. LIFETIME (selamanya)")

pilih = input("\nPilihan (1-4): ").strip()
edition_map = {"1":"BULANAN","2":"3BULAN","3":"TAHUNAN","4":"LIFETIME"}
edition = edition_map.get(pilih, "BULANAN")

machine_id = input("Machine ID user (kosongkan jika ANY): ").strip()
if not machine_id:
    machine_id = "ANY"

kode = LicenseGenerator.generate(edition=edition, machine_id=machine_id)

print("\n" + "=" * 50)
print(f"  Kode Lisensi : {kode}")
print(f"  Edition      : {edition}")
print(f"  Machine ID   : {machine_id}")
print("=" * 50)
input("\nTekan Enter untuk keluar...")