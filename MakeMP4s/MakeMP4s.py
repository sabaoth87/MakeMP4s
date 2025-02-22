import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import ffmpeg
import os
from pathlib import Path
import threading
import mimetypes
from typing import List, Tuple
import logging
import subprocess
import sys
from datetime import datetime

class VideoConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Converter")
        self.root.geometry("800x600")
        
        # Setup logging
        self.setup_logging()
        
        # Supported formats in Windows Media Player
        self.supported_formats = {'.wmv', '.asf', '.avi', '.mp4', '.m4v', '.mov', '.3gp', '.3g2'}
        self.unsupported_files = []
        
        # Check ffmpeg installation
        self.check_ffmpeg()
        
        # Create main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Add debug checkbox
        self.debug_var = tk.BooleanVar(value=False)
        self.debug_check = ttk.Checkbutton(self.main_frame, text="Debug Mode", 
                                         variable=self.debug_var, 
                                         command=self.toggle_debug)
        self.debug_check.grid(row=0, column=2, sticky=tk.E)
        
        # Folder selection
        ttk.Label(self.main_frame, text="Scan Folder:").grid(row=1, column=0, sticky=tk.W)
        self.folder_path = tk.StringVar()
        ttk.Entry(self.main_frame, textvariable=self.folder_path, width=50).grid(row=1, column=1, padx=5)
        ttk.Button(self.main_frame, text="Browse", command=self.select_folder).grid(row=1, column=2)
        
        # Rest of the UI components remain the same as before...
        [Previous UI setup code...]

        # Add log display
        self.log_frame = ttk.LabelFrame(self.main_frame, text="Log Output", padding="5")
        self.log_frame.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        self.log_text = tk.Text(self.log_frame, height=6, width=70)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Add log scrollbar
        log_scrollbar = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        # Hide log frame by default
        self.log_frame.grid_remove()

    def setup_logging(self):
        """Configure logging to both file and custom handler"""
        self.log_folder = "logs"
        if not os.path.exists(self.log_folder):
            os.makedirs(self.log_folder)
            
        log_file = os.path.join(self.log_folder, 
                               f"converter_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        # Configure logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

    def log_message(self, message: str, level: str = "info"):
        """Log message to both file and UI"""
        if level == "debug" and not self.debug_var.get():
            return
            
        # Log to file
        log_func = getattr(self.logger, level)
        log_func(message)
        
        # Update UI
        self.root.after(0, self.update_log_display, f"{level.upper()}: {message}\n")

    def update_log_display(self, message: str):
        """Update log display in UI"""
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)

    def toggle_debug(self):
        """Toggle debug log display"""
        if self.debug_var.get():
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()

    def check_ffmpeg(self):
        """Verify ffmpeg is installed and accessible"""
        try:
            subprocess.run(['ffmpeg', '-version'], 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
            self.log_message("FFmpeg installation verified", "debug")
        except FileNotFoundError:
            self.log_message("FFmpeg not found in system PATH", "error")
            messagebox.showerror("Error", 
                               "FFmpeg not found. Please install FFmpeg and add it to your system PATH.")
            sys.exit(1)

    def convert_files(self, files):
        try:
            self.log_message(f"Starting conversion of {len(files)} files", "info")
            
            for i, input_path in enumerate(files, 1):
                try:
                    self.log_message(f"Processing file {i}/{len(files)}: {input_path}", "debug")
                    
                    # Update status
                    self.root.after(0, lambda: self.status_var.set(
                        f"Converting file {i} of {len(files)}: {os.path.basename(input_path)}"
                    ))
                    
                    # Create output filename
                    input_filename = Path(input_path).stem
                    output_path = os.path.join(
                        self.output_path.get(),
                        f"{input_filename}.{self.output_format.get()}"
                    )
                    
                    self.log_message(f"Output path: {output_path}", "debug")
                    
                    # Prepare ffmpeg command
                    try:
                        # Run ffmpeg directly instead of using ffmpeg-python
                        command = [
                            'ffmpeg',
                            '-i', input_path,
                            '-c:v', 'libx264',
                            '-c:a', 'aac',
                            '-y',  # Overwrite output files
                            output_path
                        ]
                        
                        self.log_message(f"FFmpeg command: {' '.join(command)}", "debug")
                        
                        # Run conversion
                        process = subprocess.Popen(
                            command,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            universal_newlines=True
                        )
                        
                        # Monitor conversion progress
                        stdout, stderr = process.communicate()
                        
                        if process.returncode != 0:
                            raise Exception(f"FFmpeg error: {stderr}")
                            
                        self.log_message(f"Successfully converted: {input_path}", "info")
                        
                        # Verify output file exists and has size > 0
                        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                            raise Exception("Output file is missing or empty")
                            
                    except Exception as e:
                        self.log_message(f"Conversion failed: {str(e)}", "error")
                        raise
                    
                    # Update progress
                    self.root.after(0, lambda: self.overall_progress.step())
                    
                except Exception as e:
                    self.log_message(f"Error processing {input_path}: {str(e)}", "error")
                    messagebox.showerror("Conversion Error",
                                       f"Error converting {os.path.basename(input_path)}: {str(e)}")
                
            self.root.after(0, self.conversion_complete)
            
        except Exception as e:
            self.log_message(f"Fatal conversion error: {str(e)}", "error")
            self.root.after(0, lambda: self.status_var.set(f"Conversion error: {str(e)}"))
            self.root.after(0, self.conversion_complete)

    def conversion_complete(self):
        self.current_progress.stop()
        self.status_var.set("Conversion completed!")
        self.convert_btn.state(['!disabled'])
        self.log_message("Conversion process finished", "info")

    # Other methods remain the same...

def main():
    root = tk.Tk()
    app = VideoConverter(root)
    root.mainloop()

if __name__ == "__main__":
    main()