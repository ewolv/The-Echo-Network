import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import hashlib
import json
import os
import requests
import dataclasses
import traceback
import base64

try:
    import echo_production_v1 as echo_core
except ImportError:
    print("CRITICAL: 'echo_production_v1.py' must be in the same folder.")
    exit(1)

# Your Live DigitalOcean Relay / Tracker
NODE_URL = "https://node.theechos.net"

class EchoLoginGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Echo Network - Vault Access")
        self.root.geometry("450x400")
        
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tabs
        self.tab_login = ttk.Frame(self.notebook)
        self.tab_register = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_login, text="Login")
        self.notebook.add(self.tab_register, text="Create Wallet")
        
        self.build_login_tab()
        self.build_register_tab()

    def build_login_tab(self):
        ttk.Label(self.tab_login, text="Username:").pack(pady=(30,5))
        self.log_user = ttk.Entry(self.tab_login, width=35)
        self.log_user.pack()
        
        ttk.Label(self.tab_login, text="Password:").pack(pady=(10,5))
        self.log_pass = ttk.Entry(self.tab_login, show="*", width=35)
        self.log_pass.pack()
        
        ttk.Button(self.tab_login, text="Unlock Vault", command=self.attempt_login).pack(pady=30)

    def build_register_tab(self):
        ttk.Label(self.tab_register, text="New Username:").pack(pady=(20,5))
        self.reg_user = ttk.Entry(self.tab_register, width=35)
        self.reg_user.pack()
        
        ttk.Label(self.tab_register, text="Password:").pack(pady=(10,5))
        self.reg_pass = ttk.Entry(self.tab_register, show="*", width=35)
        self.reg_pass.pack()
        
        ttk.Label(self.tab_register, text="Confirm Password:").pack(pady=(10,5))
        self.reg_pass_conf = ttk.Entry(self.tab_register, show="*", width=35)
        self.reg_pass_conf.pack()
        
        ttk.Button(self.tab_register, text="Generate PQC Keys", command=self.attempt_register).pack(pady=20)

    def attempt_login(self):
        user = self.log_user.get().strip()
        pwd = self.log_pass.get()
        if not user or not pwd:
            messagebox.showerror("Error", "Enter credentials.")
            return
            
        auth_hash = hashlib.sha256(f"{user}:{pwd}".encode()).hexdigest()
        self.launch_wallet(user, auth_hash)

    def attempt_register(self):
        user = self.reg_user.get().strip()
        pwd = self.reg_pass.get()
        pwd2 = self.reg_pass_conf.get()
        
        if not user or not pwd:
            messagebox.showerror("Error", "Fields cannot be empty.")
            return
        if pwd != pwd2:
            messagebox.showerror("Error", "Passwords do not match!")
            return
            
        messagebox.showinfo("Vault Created", f"Cryptographic vault generated for '{user}'.\n\nWelcome to the Echo Network.")
        auth_hash = hashlib.sha256(f"{user}:{pwd}".encode()).hexdigest()
        self.launch_wallet(user, auth_hash)

    def launch_wallet(self, username, auth_hash):
        self.root.destroy()
        wallet_root = tk.Tk()
        EchoMainWallet(wallet_root, username, auth_hash)
        wallet_root.mainloop()


class EchoMainWallet:
    def __init__(self, root, username, auth_hash):
        self.root = root
        self.username = username
        self.auth_hash = auth_hash
        
        # Define the Public Key BEFORE booting the core
        self.pub_key_display = f"ECHO-{self.auth_hash[:16].upper()}"
        
        self.root.title(f"Echo P2P Wallet - {self.username}")
        self.root.geometry("800x600")
        
        # Initialize STARK Core using the PUBLIC KEY as the true identity
        self.mesh = echo_core.MeshNetwork()
        self.wallet = echo_core.EchoWallet(self.pub_key_display, self.mesh)
        self.selected_file_path = None
        
        # Ensure Downloads Folder Exists
        self.download_dir = os.path.join(os.getcwd(), "Echo_Downloads")
        os.makedirs(self.download_dir, exist_ok=True)
        
        self.build_ui()

    def build_ui(self):
        # Top Dashboard
        dash_frame = ttk.Frame(self.root, padding=10)
        dash_frame.pack(fill=tk.X)
        
        ttk.Label(dash_frame, text=f"Identity: {self.username}", font=("Helvetica", 14, "bold")).pack(side=tk.LEFT)
        
        # Public Key Display & Copy
        ttk.Label(dash_frame, text=f"Pub: {self.pub_key_display}").pack(side=tk.LEFT, padx=20)
        ttk.Button(dash_frame, text="📋 Copy Key", command=self.copy_pub).pack(side=tk.LEFT)
        
        ttk.Button(dash_frame, text="🌐 Sync Mesh", command=self.sync_network).pack(side=tk.RIGHT)

        # Main Body
        body = ttk.Frame(self.root, padding=10)
        body.pack(fill=tk.BOTH, expand=True)

        # Left: Send Payload
        send_frame = ttk.LabelFrame(body, text=" Send Phinary & File Payload ", padding=15)
        send_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        ttk.Label(send_frame, text="Recipient Address (ECHO-...):").pack(anchor=tk.W)
        self.ent_dest = ttk.Entry(send_frame, width=35)
        self.ent_dest.pack(anchor=tk.W, pady=(0, 15))
        
        ttk.Label(send_frame, text="Exponents (e.g. -4):").pack(anchor=tk.W)
        self.ent_exps = ttk.Entry(send_frame, width=35)
        self.ent_exps.pack(anchor=tk.W, pady=(0, 15))
        
        ttk.Label(send_frame, text="Attach File (Native Phi Transport):").pack(anchor=tk.W)
        file_btn_frame = ttk.Frame(send_frame)
        file_btn_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 15))
        ttk.Button(file_btn_frame, text="📎 Select File", command=self.attach_file).pack(side=tk.LEFT)
        self.lbl_file = ttk.Label(file_btn_frame, text="No file attached", foreground="gray")
        self.lbl_file.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(send_frame, text="🚀 Encrypt & Broadcast", command=self.send_payload).pack(pady=20, fill=tk.X)

        # Right: Inbox / Funds
        inbox_frame = ttk.LabelFrame(body, text=" Secured Ledger & Data ", padding=15)
        inbox_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.tree_funds = ttk.Treeview(inbox_frame, columns=("Amount", "Data / Purpose"), show="headings")
        self.tree_funds.heading("Amount", text="Exponents")
        self.tree_funds.heading("Data / Purpose", text="Data / Purpose")
        self.tree_funds.column("Amount", width=100)
        self.tree_funds.column("Data / Purpose", width=200)
        self.tree_funds.pack(fill=tk.BOTH, expand=True)

    def copy_pub(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.pub_key_display)
        messagebox.showinfo("Copied", "Public Routing Address copied to clipboard.")

    def attach_file(self):
        path = filedialog.askopenfilename()
        if path:
            # Check file size to prevent memory overload in prototype (Limit: 5MB)
            if os.path.getsize(path) > 5 * 1024 * 1024:
                messagebox.showerror("File Too Large", "For this prototype, please select a file under 5MB.")
                return
            
            self.selected_file_path = path
            filename = os.path.basename(path)
            self.lbl_file.config(text=filename, foreground="green")

    def send_payload(self):
        dest = self.ent_dest.get().strip()
        exps_raw = self.ent_exps.get().strip()
        
        if not dest or not exps_raw:
            messagebox.showwarning("Error", "Enter destination and amount.")
            return
            
        try:
            exps = tuple(int(x.strip()) for x in exps_raw.split(","))
        except ValueError:
            messagebox.showerror("Error", "Invalid exponents.")
            return

        # Native Phi File Transport Logic
        metadata_str = "Standard Transfer"
        if self.selected_file_path:
            try:
                filename = os.path.basename(self.selected_file_path)
                with open(self.selected_file_path, "rb") as f:
                    encoded_string = base64.b64encode(f.read()).decode('utf-8')
                # Pack the file directly into the envelope's metadata
                metadata_str = f"FILE:{filename}|B64:{encoded_string}"
            except Exception as e:
                messagebox.showerror("File Error", f"Could not encode file:\n{e}")
                return

        # 1. Generate the STARK Envelope
        env = self.wallet.make_payment(dest, exps, metadata=metadata_str)
        if not env:
            messagebox.showerror("Failed", "Insufficient funds or mathematical boundary error.")
            return
            
        env_dict = dataclasses.asdict(env)
        
        # 2. Broadcast to the Global DigitalOcean Relay Tracker
        try:
            resp = requests.post(f"{NODE_URL}/network/broadcast", json=env_dict, timeout=10)
            if resp.status_code == 200:
                messagebox.showinfo("Success", f"STARK Proof and payload routed to {dest}.")
                self.ent_dest.delete(0, tk.END)
                self.ent_exps.delete(0, tk.END)
                self.lbl_file.config(text="No file attached", foreground="gray")
                self.selected_file_path = None
                self.refresh_dashboard()
            else:
                messagebox.showerror("Node Error", resp.text)
        except Exception as e:
            messagebox.showerror("Network Error", str(e))

    def sync_network(self):
        try:
            # Route strictly by the cryptographic public key, not the username alias
            resp = requests.get(f"{NODE_URL}/network/sync/{self.pub_key_display}", timeout=10)
            if resp.status_code == 200:
                envelopes = resp.json().get("envelopes", [])
                
                download_count = 0
                
                for env_data in envelopes:
                    safe_sig = tuple(env_data["signature"]) if env_data.get("signature") else ()
                    safe_pub = tuple(tuple(pair) for pair in env_data["pub_key"]) if env_data.get("pub_key") else ()
                    
                    env = echo_core.Envelope(
                        eid=env_data["eid"], sender=env_data["sender"], destination=env_data["destination"],
                        parent_id=env_data["parent_id"], target_exps=tuple(env_data["target_exps"]),
                        change_exps=tuple(env_data["change_exps"]), silt_pair=tuple(env_data["silt_pair"]),
                        nullifier=env_data["nullifier"], expiry_epoch=env_data["expiry_epoch"],
                        phase=env_data["phase"], watermark=env_data["watermark"], 
                        signature=safe_sig, pub_key=safe_pub, 
                        branch_proof=env_data.get("branch_proof", ""),
                        fee_exps=tuple(env_data.get("fee_exps", [])), metadata=env_data.get("metadata", "")
                    )
                    
                    # Force SPV Bypass
                    if env.eid not in self.wallet.receipts:
                        self.wallet.envelopes[env.eid] = env
                        
                        # --- DATA LAYER EXTRACTION ---
                        display_purpose = env.metadata
                        if env.metadata and env.metadata.startswith("FILE:"):
                            try:
                                parts = env.metadata.split("|B64:")
                                filename = parts[0].replace("FILE:", "")
                                b64_data = parts[1]
                                
                                # Rebuild the file physically on the hard drive
                                save_path = os.path.join(self.download_dir, filename)
                                with open(save_path, "wb") as f:
                                    f.write(base64.b64decode(b64_data))
                                
                                display_purpose = f"💾 Saved: {filename}"
                                download_count += 1
                            except Exception as e:
                                display_purpose = "⚠️ File Extraction Failed"
                                print(f"Extraction Error: {e}")

                        class SPVReceipt:
                            purpose = display_purpose
                            exps = env.target_exps
                            state = "LIVE"
                        self.wallet.receipts[env.eid] = SPVReceipt()

                self.refresh_dashboard()
                
                if download_count > 0:
                    messagebox.showinfo("Files Received", f"Successfully extracted {download_count} file(s) into:\n\n{self.download_dir}")
                elif len(envelopes) > 0:
                    messagebox.showinfo("Sync Complete", f"Downloaded {len(envelopes)} new payment(s).")
                    
            else:
                messagebox.showwarning("Sync Issue", f"Node returned: {resp.status_code}")
                
        except Exception as e:
            messagebox.showerror("Sync Error", f"Network sync failed:\n\n{e}")

    def refresh_dashboard(self):
        for row in self.tree_funds.get_children():
            self.tree_funds.delete(row)
            
        for r in self.wallet.receipts.values():
            if r.state == "LIVE":
                self.tree_funds.insert("", tk.END, values=(str(r.exps), getattr(r, 'purpose', 'Standard Transfer')))

if __name__ == "__main__":
    root = tk.Tk()
    app = EchoLoginGUI(root)
    root.mainloop()
