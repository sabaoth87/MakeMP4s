import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import ffmpeg
import os
import re
from pathlib import Path
import threading
import mimetypes
from typing import Optional, Tuple, List
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime

@dataclass
class MediaInfo:
    title: str
    year: Optional[str] = None
    season: Optional[str] = None
    episode: Optional[str] = None

class FilenameParser:
    def __init__(self):
        # Patterns for different filename formats
        self.movie_patterns = [
            # Pattern: Movie.Name.2024.1080p...
            r'^((?:[A-Za-z0-9.]+[. ])*?)(?:[\[(]?(\d{4})[\])]?)',
            # Pattern: Movie.Name.(2024)...
            r'^((?:[A-Za-z0-9.]+[. ])*?)\((\d{4})\)',
        ]
        
        self.tv_patterns = [
            # Pattern: Show.Name.S01E02...
            r'^((?:[A-Za-z0-9.]+[. ])*?)S(\d{1,2})E(\d{1,2})',
            # Pattern: Show.Name.1x02...
            r'^((?:[A-Za-z0-9.]+[. ])*?)(\d{1,2})x(\d{1,2})',
        ]

    def clean_title(self, title: str) -> str:
        """Clean up title by replacing dots/underscores with spaces and proper capitalization"""
        # Replace dots and underscores with spaces
        title = re.sub(r'[._]', ' ', title)
        # Remove any remaining unwanted characters
        title = re.sub(r'[^\w\s-]', '', title)
        # Proper title case
        title = ' '.join(word.capitalize() for word in title.split())
        return title.strip()

    def parse_filename(self, filename: str) -> MediaInfo:
        """Parse filename and extract media information"""
        # Try TV show patterns first
        for pattern in self.tv_patterns:
            match = re.match(pattern, filename)
            if match:
                title = self.clean_title(match.group(1))
                return MediaInfo(
                    title=title,
                    season=str(int(match.group(2))),  # Remove leading zeros
                    episode=str(int(match.group(3)))
                )
        
        # Try movie patterns
        for pattern in self.movie_patterns:
            match = re.match(pattern, filename)
            if match:
                title = self.clean_title(match.group(1))
                return MediaInfo(
                    title=title,
                    year=match.group(2)
                )
        
        # If no pattern matches, just clean the filename
        return MediaInfo(title=self.clean_title(filename))

    def generate_filename(self, media_info: MediaInfo) -> str:
        """Generate clean filename from MediaInfo"""
        if media_info.season and media_info.episode:
            # TV Show format: "Show Name - S01E02"
            return f"{media_info.title} - S{media_info.season.zfill(2)}E{media_info.episode.zfill(2)}"
        elif media_info.year:
            # Movie format: "Movie Name (2024)"
            return f"{media_info.title} ({media_info.year})"
        else:
            # Just the clean title
            return media_info.title

class VideoConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("TaNK Makes MP4s")
        self.root.geometry("800x600")
        
        # Initialize filename parser
        self.filename_parser = FilenameParser()

        # Setup logging
        self.setup_logging()

        # Supported formats in Windows Media Player
        self.supported_formats = {'.wmv', '.asf', '.avi', '.mp4', '.m4v', '.mov', '.3gp', '.3g2'}
        self.unsupported_files = []

        # Create main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Folder selection
        ttk.Label(self.main_frame, text="Scan Folder:").grid(row=0, column=0, sticky=tk.W)
        self.folder_path = tk.StringVar()
        ttk.Entry(self.main_frame, textvariable=self.folder_path, width=50).grid(row=0, column=1, padx=5)
        ttk.Button(self.main_frame, text="Browse", command=self.select_folder).grid(row=0, column=2)
        
         # Add debug checkbox
        self.debug_var = tk.BooleanVar(value=False)
        self.debug_check = ttk.Checkbutton(self.main_frame, text="Debug Mode", 
                                         variable=self.debug_var, 
                                         command=self.toggle_debug)
        self.debug_check.grid(row=0, column=3, sticky=tk.E)

        # Scan button
        ttk.Button(self.main_frame, text="Scan for Unsupported Videos", 
                  command=self.start_scan).grid(row=1, column=0, columnspan=3, pady=10)
        
        # Results list
        ttk.Label(self.main_frame, text="Unsupported Videos Found:").grid(row=2, column=0, columnspan=3, sticky=tk.W)
        
        # Create frame for treeview and scrollbar
        tree_frame = ttk.Frame(self.main_frame)
        tree_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Treeview for file list
        self.file_tree = ttk.Treeview(tree_frame, columns=('Path', 'Size', 'Type'), 
                                     show='headings', height=10)
        self.file_tree.heading('Path', text='Path')
        self.file_tree.heading('Size', text='Size')
        self.file_tree.heading('Type', text='Type')
        self.file_tree.column('Path', width=400)
        self.file_tree.column('Size', width=100)
        self.file_tree.column('Type', width=100)
        self.file_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.file_tree.configure(yscrollcommand=scrollbar.set)
        
        # Output directory selection
        ttk.Label(self.main_frame, text="Output Directory:").grid(row=4, column=0, sticky=tk.W, pady=10)
        self.output_path = tk.StringVar()
        ttk.Entry(self.main_frame, textvariable=self.output_path, width=50).grid(row=4, column=1, padx=5)
        ttk.Button(self.main_frame, text="Browse", command=self.select_output).grid(row=4, column=2)
        
        # Format selection
        ttk.Label(self.main_frame, text="Convert to:").grid(row=5, column=0, sticky=tk.W)
        self.output_format = tk.StringVar(value="mp4")
        format_combo = ttk.Combobox(self.main_frame, textvariable=self.output_format,
                                  values=["mp4", "avi"], state="readonly")
        format_combo.grid(row=5, column=1, sticky=tk.W, padx=5)
        
        # Progress frame
        progress_frame = ttk.LabelFrame(self.main_frame, text="Conversion Progress", padding="5")
        progress_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # Overall progress
        ttk.Label(progress_frame, text="Overall:").grid(row=0, column=0, sticky=tk.W)
        self.overall_progress = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.overall_progress.grid(row=0, column=1, padx=5)
        
        # Current file progress
        ttk.Label(progress_frame, text="Current:").grid(row=1, column=0, sticky=tk.W)
        self.current_progress = ttk.Progressbar(progress_frame, length=400, mode='indeterminate')
        self.current_progress.grid(row=1, column=1, padx=5)
        
        # Status label
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(self.main_frame, textvariable=self.status_var)
        self.status_label.grid(row=7, column=0, columnspan=3)
        
        # Convert button
        self.convert_btn = ttk.Button(self.main_frame, text="Convert Selected Files",
                                    command=self.start_conversion)
        self.convert_btn.grid(row=8, column=0, columnspan=3, pady=10)
        self.convert_btn.state(['disabled'])

        # Add log display
        self.log_frame = ttk.LabelFrame(self.main_frame, text="Log Output", padding="5")
        self.log_frame.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        self.log_text = tk.Text(self.log_frame, height=6, width=70)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Add log scrollbar
        log_scrollbar = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        # Add filename preview frame
        self.preview_frame = ttk.LabelFrame(self.main_frame, text="Filename Preview", padding="5")
        self.preview_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # Preview tree
        self.preview_tree = ttk.Treeview(self.preview_frame, 
                                       columns=('Original', 'New Name'),
                                       show='headings',
                                       height=5)
        self.preview_tree.heading('Original', text='Original Filename')
        self.preview_tree.heading('New Name', text='New Filename')
        self.preview_tree.column('Original', width=350)
        self.preview_tree.column('New Name', width=350)
        self.preview_tree.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Preview scrollbar
        preview_scrollbar = ttk.Scrollbar(self.preview_frame, orient=tk.VERTICAL, 
                                        command=self.preview_tree.yview)
        preview_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.preview_tree.configure(yscrollcommand=preview_scrollbar.set)

        # Hide log frame by default
        self.log_frame.grid_remove()

         # Check and setup ffmpeg
        if not self.setup_ffmpeg():
            return

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
        """ Toggle debug log display """
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


    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)

    def select_output(self):
        directory = filedialog.askdirectory()
        if directory:
            self.output_path.set(directory)

    def get_file_size(self, file_path: str) -> str:
        """Convert file size to human readable format"""
        size = os.path.getsize(file_path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def scan_directory(self, directory: str) -> List[Tuple[str, str, str]]:
        """Recursively scan directory for video files"""
        video_files = []
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                file_ext = os.path.splitext(file)[1].lower()
                mime_type = mimetypes.guess_type(file_path)[0]
                
                # Check if file is a video and not in supported formats
                if (mime_type and mime_type.startswith('video/') and 
                    file_ext not in self.supported_formats):
                    size = self.get_file_size(file_path)
                    video_files.append((file_path, size, file_ext))
        return video_files

    def start_scan(self):
        if not self.folder_path.get():
            messagebox.showerror("Error", "Please select a folder to scan")
            return
            
        # Clear previous results
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        
        self.status_var.set("Scanning for unsupported videos...")
        self.convert_btn.state(['disabled'])
        
        # Start scan in separate thread
        thread = threading.Thread(target=self.perform_scan)
        thread.daemon = True
        thread.start()

    def perform_scan(self):
        try:
            unsupported_files = self.scan_directory(self.folder_path.get())
            
            # Update UI in main thread
            self.root.after(0, self.update_scan_results, unsupported_files)
            
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Scan error: {str(e)}"))

    def update_scan_results(self, files):
        """Update scan results and show filename previews"""
        # Clear previous results
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        
        for file_path, size, file_type in files:
            # Add to main file list
            self.file_tree.insert('', 'end', values=(file_path, size, file_type))
            
            # Generate and show filename preview
            original_name = Path(file_path).stem
            media_info = self.filename_parser.parse_filename(original_name)
            new_name = self.filename_parser.generate_filename(media_info)
            
            self.preview_tree.insert('', 'end', values=(original_name, new_name))
        
        self.status_var.set(f"Found {len(files)} unsupported video files")
        if files:
            self.convert_btn.state(['!disabled'])

    def start_conversion(self):
        if not self.output_path.get():
            messagebox.showerror("Error", "Please select output directory")
            return
            
        selected_items = self.file_tree.selection()
        if not selected_items:
            messagebox.showerror("Error", "Please select files to convert")
            return
            
        # Get list of selected files
        files_to_convert = [
            self.file_tree.item(item)['values'][0]
            for item in selected_items
        ]
        
        # Disable buttons during conversion
        self.convert_btn.state(['disabled'])
        
        # Reset and configure progress bars
        self.overall_progress['value'] = 0
        self.overall_progress['maximum'] = len(files_to_convert)
        self.current_progress.start()
        
        # Start conversion in separate thread
        thread = threading.Thread(target=self.convert_files, args=(files_to_convert,))
        thread.daemon = True
        thread.start()

    def convert_files(self, files):
        try:
            self.log_message(f"Starting conversion of {len(files)} files", "info")
            
            # Get ffmpeg path
            ffmpeg_path = 'ffmpeg'  # default to PATH
            if os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe"):
                ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"
            
            for i, input_path in enumerate(files, 1):
                try:
                    self.log_message(f"Processing file {i}/{len(files)}: {input_path}", "debug")
                    
                    # Update status
                    self.root.after(0, lambda: self.status_var.set(
                        f"Converting file {i} of {len(files)}: {os.path.basename(input_path)}"
                    ))
                    
                    # Generate new filename
                    input_filename = Path(input_path).stem
                    media_info = self.filename_parser.parse_filename(input_filename)
                    new_filename = self.filename_parser.generate_filename(media_info)
                    
                    output_path = os.path.join(
                        self.output_path.get(),
                        f"{new_filename}.{self.output_format.get()}"
                    )
                    
                    self.log_message(f"Output path: {output_path}", "debug")

                    # Prepare ffmpeg command with full path
                    command = [
                        ffmpeg_path,
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
                    
                    # Verify output file
                    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                        raise Exception("Output file is missing or empty")
                    
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

    def setup_ffmpeg(self) -> bool:
        """
        Verify and setup FFmpeg, with detailed error reporting
        Returns True if FFmpeg is properly configured
        """
        self.log_message("Checking FFmpeg installation...", "info")
        
        # List of possible FFmpeg paths
        ffmpeg_paths = [
            r"C:\ffmpeg\bin",
            r"C:\ffmpeg",
            os.path.expanduser("~\\ffmpeg\\bin"),
            os.path.expanduser("~\\ffmpeg")
        ]
        
        # Get current PATH
        current_path = os.environ.get('PATH', '')
        self.log_message(f"Current PATH: {current_path}", "debug")
        
        # Check if ffmpeg is directly accessible
        try:
            subprocess.run(['ffmpeg', '-version'], 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
            self.log_message("FFmpeg found in system PATH", "info")
            return True
        except FileNotFoundError:
            self.log_message("FFmpeg not found in system PATH, checking additional locations...", "debug")
        
        # Check additional paths
        ffmpeg_exe = None
        for path in ffmpeg_paths:
            potential_path = os.path.join(path, "ffmpeg.exe")
            self.log_message(f"Checking {potential_path}", "debug")
            
            if os.path.isfile(potential_path):
                ffmpeg_exe = potential_path
                self.log_message(f"Found FFmpeg at: {ffmpeg_exe}", "info")
                break
        
        if ffmpeg_exe:
            # Add FFmpeg to PATH for this session
            ffmpeg_dir = os.path.dirname(ffmpeg_exe)
            if ffmpeg_dir not in current_path:
                os.environ['PATH'] = ffmpeg_dir + os.pathsep + current_path
                self.log_message(f"Added FFmpeg directory to PATH: {ffmpeg_dir}", "info")
            
            # Verify FFmpeg now works
            try:
                result = subprocess.run([ffmpeg_exe, '-version'], 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE,
                                     text=True)
                self.log_message(f"FFmpeg version: {result.stdout.split('n')[0]}", "info")
                return True
            except Exception as e:
                self.log_message(f"Error running FFmpeg: {str(e)}", "error")
        
        # FFmpeg not found or not working
        error_message = (
            "FFmpeg not found or not working properly.\n\n"
            "Please ensure FFmpeg is installed at C:\\ffmpeg\\bin and added to your system PATH.\n\n"
            "Installation steps:\n"
            "1. Download FFmpeg from https://ffmpeg.org/download.html\n"
            "2. Extract to C:\\ffmpeg\n"
            "3. Add C:\\ffmpeg\\bin to your system PATH:\n"
            "   - Open System Properties → Advanced → Environment Variables\n"
            "   - Under System Variables, find and select 'Path'\n"
            "   - Click Edit → New\n"
            "   - Add 'C:\\ffmpeg\\bin'\n"
            "   - Click OK on all windows\n"
            "4. Restart your computer\n"
            "5. Restart this application"
        )
        
        self.log_message(error_message, "error")
        messagebox.showerror("FFmpeg Setup Required", error_message)
        return False

def main():
    root = tk.Tk()
    app = VideoConverter(root)
    root.mainloop()

if __name__ == "__main__":
    main()