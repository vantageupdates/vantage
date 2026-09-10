// Native-width Group gauges, preserving source shading and unscaled end caps.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;

public static class VantageGroupBars {
    static void Part(Bitmap source,Bitmap atlas,int sx,int sy,int sw,int height,int dy,int width) {
        const int cap=4;
        for(int y=0;y<height;y++)for(int x=0;x<width;x++) {
            int ox=x<cap?x:x>=width-cap?sw-(width-x):
                cap+(int)Math.Round((x-cap)*(sw-2*cap-1.0)/(width-2*cap-1));
            atlas.SetPixel(2+x,dy+y,source.GetPixel(sx+ox,sy+y));
        }
    }
    static void ExpSeparators(Bitmap atlas,int dy,int width,bool background) {
        // Five restrained sections with a crisp one-pixel divider. Keep the
        // rounded end caps, surrounding fill gradient, and highlights untouched.
        for(int section=1;section<5;section++) {
            int center=2+(int)Math.Round(width*section/5.0);
            for(int y=dy+3;y<dy+17;y++) {
                var color=atlas.GetPixel(center,y);
                if(background) {
                    var target=Color.FromArgb(110,76,25); // Deep EXP gold.
                    const double mix=.82;
                    atlas.SetPixel(center,y,Color.FromArgb(color.A,
                        (int)Math.Round(color.R*(1-mix)+target.R*mix),
                        (int)Math.Round(color.G*(1-mix)+target.G*mix),
                        (int)Math.Round(color.B*(1-mix)+target.B*mix)));
                } else {
                    // This grayscale frame receives the native gold FillTint.
                    const double factor=.64;
                    atlas.SetPixel(center,y,Color.FromArgb(color.A,
                        (int)Math.Round(color.R*factor),(int)Math.Round(color.G*factor),
                        (int)Math.Round(color.B*factor)));
                }
            }
        }
    }
    static void ColorizeLines(Bitmap atlas,int sourceY,int destinationY,int width,Color tone) {
        for(int y=0;y<10;y++)for(int x=0;x<width;x++) {
            var source=atlas.GetPixel(2+x,sourceY+y);
            atlas.SetPixel(2+x,destinationY+y,source.A==0?Color.Transparent:
                Color.FromArgb(source.A,tone.R,tone.G,tone.B));
        }
    }
    public static void Render(string sourcePath,string destination,string preview) {
        if(Path.GetFileName(destination)!="VantageGroupBars.tga")
            throw new ArgumentException("Expected the dedicated Group atlas.");
        using(var source=new Bitmap(sourcePath))
        using(var atlas=new Bitmap(256,128,PixelFormat.Format32bppArgb)) {
            Part(source,atlas,0,20,104,20,2,145);  // EXP background.
            Part(source,atlas,2,0,100,20,26,141);  // EXP fill, inset 2px.
            ExpSeparators(atlas,2,145,true);
            ExpSeparators(atlas,26,141,false);
            Part(source,atlas,0,90,104,10,50,145); // Thin background.
            Part(source,atlas,0,80,104,10,64,145); // Thin fill.
            Part(source,atlas,0,110,104,10,78,145);// Thin separators.
            ColorizeLines(atlas,78,92,145,Color.FromArgb(20,104,126)); // Breath.
            ColorizeLines(atlas,78,78,145,Color.FromArgb(127,76,8));   // Fatigue.
            using(var writer=new BinaryWriter(File.Create(destination))) {
                var header=new byte[18];header[2]=2;header[13]=1;header[14]=128;
                header[16]=32;header[17]=40;writer.Write(header);
                for(int y=0;y<128;y++)for(int x=0;x<256;x++) {
                    var c=atlas.GetPixel(x,y);writer.Write(c.B);writer.Write(c.G);writer.Write(c.R);writer.Write(c.A);
                }
            }
            if(!String.IsNullOrEmpty(preview))atlas.Save(preview,ImageFormat.Png);
        }
    }
}
