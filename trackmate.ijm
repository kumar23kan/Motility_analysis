// trackmate.ijm
// Runs LoG detection + Simple LAP tracker on all .tif/.tiff files
// in the images/ folder next to this macro.
//
// To run from command line:
//   fiji --headless -macro /path/to/trackmate.ijm

// Use the folder containing this macro as the base directory
macroDir = File.getParent(getInfo("macro.filepath"));
input    = macroDir + File.separator + "images" + File.separator;
output   = macroDir + File.separator + "output" + File.separator;

File.makeDirectory(output);

list = getFileList(input);

for (i = 0; i < list.length; i++) {

    name = list[i];
    if (!endsWith(name, ".tif") && !endsWith(name, ".tiff")) continue;

    print("Processing: " + name);
    open(input + name);

    run("Gaussian Blur...", "sigma=1");
    run("8-bit");

    // TrackMate: LoG detector, Simple LAP tracker
    run("TrackMate", "detector=LoG radius=5 threshold=5 tracker=Simple LAP");

    saveAs("Results", output + "results_" + name + ".csv");
    close();
}

print("DONE");
