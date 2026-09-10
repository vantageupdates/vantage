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
    public static void Render(string sourcePath,string destination,string preview) {
        if(Path.GetFileName(destination)!="VantageGroupBars.tga")
            throw new ArgumentException("Expected the dedicated Group atlas.");
        using(var source=new Bitmap(sourcePath))
        using(var atlas=new Bitmap(256,128,PixelFormat.Format32bppArgb)) {
            Part(source,atlas,0,20,104,20,2,145);  // EXP background.
            Part(source,atlas,2,0,100,20,26,141);  // EXP fill, inset 2px.
            Part(source,atlas,0,90,104,10,50,145); // Thin background.
            Part(source,atlas,0,80,104,10,64,145); // Thin fill.
            Part(source,atlas,0,110,104,10,78,145);// Thin separators.
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
