from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path.cwd()
logs = ('phase7_standard.txt', 'phase7_resourcewarning.txt', 'phase7_api.txt')
for name in logs:
    assert (root / '.test-tmp' / name).read_text(encoding='utf-8-sig').strip().endswith('OK'), name
with ZipFile(root / 'Exception_Genome_Phase_7.zip', 'w', ZIP_DEFLATED) as archive:
    for name in ('app.py', 'AGENTS.md', 'README.md', 'requirements.txt', 'Phase_4_Report.md',
                 'Phase_5_Report.md', 'Phase_6_Report.md', 'Phase_7_Report.md', 'API_CONTRACT.md',
                 'N8N_HANDOFF.md', '.streamlit/config.toml', 'data/seed_services.json'):
        archive.write(root / name, name)
    for folder in ('core', 'ui', 'simulator', 'tests', 'api', 'services'):
        for file in sorted((root / folder).rglob('*.py')):
            archive.write(file, file.relative_to(root))
    for name in logs:
        archive.write(root / '.test-tmp' / name, 'validation/' + name)
with ZipFile(root / 'Exception_Genome_Phase_7.zip') as archive:
    assert archive.testzip() is None
    print(len(archive.namelist()), 'verified archive entries')


