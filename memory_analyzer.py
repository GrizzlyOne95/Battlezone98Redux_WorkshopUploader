import os
import re


class MemoryAnalyzer:
    def __init__(self, logger=None, has_pil=False, image_module=None):
        self.logger = logger
        self.has_pil = has_pil
        self.image_module = image_module

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def _get_uncompressed_size(self, path):
        try:
            if self.has_pil and self.image_module is not None:
                with self.image_module.open(path) as img:
                    return (img.width * img.height * 4) * 1.33
        except Exception:
            pass
        return os.path.getsize(path) * 5

    def analyze(self, mod_dir):
        stats = {
            "disk_size": 0,
            "est_vram": 0,
            "counts": {"Texture": 0, "Model": 0, "Audio": 0, "Script": 0, "Other": 0},
        }

        non_dds_textures = []
        all_files = {}

        for root, _, files in os.walk(mod_dir):
            for name in files:
                path = os.path.join(root, name)
                all_files[name.lower()] = path
                try:
                    size = os.path.getsize(path)
                    stats["disk_size"] += size

                    ext = name.lower().split(".")[-1]

                    if ext in ["png", "tga", "bmp", "jpg", "jpeg", "tif", "tiff"]:
                        stats["counts"]["Texture"] += 1
                        stats["est_vram"] += self._get_uncompressed_size(path)
                        non_dds_textures.append(name)
                    elif ext in ["dds"]:
                        stats["counts"]["Texture"] += 1
                        stats["est_vram"] += size
                    elif ext in ["x", "geo", "xsi", "3ds"]:
                        stats["counts"]["Model"] += 1
                        stats["est_vram"] += size * 3
                    elif ext in ["wav", "ogg"]:
                        stats["counts"]["Audio"] += 1
                    elif ext in ["lua", "odf", "inf"]:
                        stats["counts"]["Script"] += 1
                    else:
                        stats["counts"]["Other"] += 1
                except Exception as e:
                    self.log(f"Skipped {name}: {e}")

        self.log("Scanning for orphaned files...")
        referenced = set()
        for name in all_files:
            if name.endswith((".ini", ".hg2", ".trn", ".mat", ".bzn", ".lgt")):
                referenced.add(name)

        asset_exts = (
            ".hg2", ".trn", ".mat", ".bzn", ".lgt", ".bmp", ".des", ".vxt",
            ".wav", ".ogg", ".tga", ".dds", ".x", ".geo", ".xsi", ".3ds", ".png", ".jpg",
        )

        for path in all_files.values():
            ext = os.path.splitext(path)[1].lower()
            if ext in (".odf", ".material", ".inf", ".lua", ".ini", ".txt"):
                try:
                    with open(path, "r", errors="ignore") as f:
                        content = f.read()
                    potential = re.findall(r'["\']([^"\'\r\n]+)["\']', content)
                    potential.extend(re.findall(r'=\s*([\w\.\-]+)', content))

                    for candidate in potential:
                        candidate_lower = candidate.lower()
                        if candidate_lower in all_files:
                            referenced.add(candidate_lower)
                        else:
                            for asset_ext in asset_exts:
                                lookup = f"{candidate_lower}{asset_ext}"
                                if lookup in all_files:
                                    referenced.add(lookup)
                except Exception:
                    pass

        orphans = [name for name in all_files if name not in referenced and not name.endswith(".ini")]
        disk_mb = stats["disk_size"] / (1024 * 1024)
        vram_mb = stats["est_vram"] / (1024 * 1024)

        return {
            "disk_mb": disk_mb,
            "vram_mb": vram_mb,
            "counts": stats["counts"],
            "non_dds_textures": non_dds_textures,
            "orphans": orphans,
        }

    def build_report(self, analysis):
        report = (
            f"MEMORY ANALYSIS REPORT\n"
            f"----------------------\n"
            f"Total Disk Size: {analysis['disk_mb']:.2f} MB\n"
            f"Est. Runtime Memory: {analysis['vram_mb']:.2f} MB\n\n"
            f"Asset Breakdown:\n"
            f"  Textures: {analysis['counts']['Texture']}\n"
            f"  Models: {analysis['counts']['Model']}\n"
            f"  Audio: {analysis['counts']['Audio']}\n"
            f"  Scripts: {analysis['counts']['Script']}\n"
        )

        if analysis["non_dds_textures"]:
            report += f"\n[!] WARNING: {len(analysis['non_dds_textures'])} non-DDS textures found.\n"
            report += "These will consume more VRAM than DDS (DXT) compressed files.\n"

        if analysis["orphans"]:
            report += f"\n[?] ORPHANS: {len(analysis['orphans'])} files appear unused:\n"
            for orphan in analysis["orphans"][:10]:
                report += f"  - {orphan}\n"
            if len(analysis["orphans"]) > 10:
                report += f"  ... and {len(analysis['orphans']) - 10} more.\n"
            report += "\n(Check carefully before deleting; scripts may use dynamic names.)"

        if analysis["vram_mb"] > 2000:
            report += f"\n\n[!] CRITICAL: Est. VRAM usage ({analysis['vram_mb']:.0f}MB) is very high!\n"
            report += "Battlezone 98 Redux may crash on lower-end hardware."
        elif analysis["vram_mb"] > 1000:
            report += f"\n\n[!] WARNING: Est. VRAM usage ({analysis['vram_mb']:.0f}MB) is high.\n"
            report += "Consider using DDS (DXT) for large textures."

        return report
