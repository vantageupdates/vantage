// Code-native skin primitives, adapted from the existing SoftGoldRenderer.
// Generates only the dedicated control-edge atlas; never processes item art.
using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class VantageControlEdgesRenderer {
    static GraphicsPath Round(float x,float y,float w,float h,float r) {
        var p=new GraphicsPath(); float d=2*r;
        p.AddArc(x,y,d,d,180,90); p.AddArc(x+w-d,y,d,d,270,90);
        p.AddArc(x+w-d,y+h-d,d,d,0,90); p.AddArc(x,y+h-d,d,d,90,90);
        p.CloseFigure(); return p;
    }
    public static void Render(string destination) {
        if(Path.GetFileName(destination)!="VantageControlEdges.tga")
            throw new ArgumentException("Only the dedicated edge atlas is supported.");
        using(var atlas=new Bitmap(512,128,PixelFormat.Format32bppArgb))
        using(var large=new Bitmap(160,160,PixelFormat.Format32bppArgb))
        using(var frame=new Bitmap(40,40,PixelFormat.Format32bppArgb)) {
            using(var g=Graphics.FromImage(large))
            using(var path=Round(2.4f,2.4f,155.2f,155.2f,8))
            using(var pen=new Pen(Color.FromArgb(120,108,91,61),2.2f)) {
                g.SmoothingMode=SmoothingMode.AntiAlias;
                g.DrawPath(pen,path);
            }
            using(var g=Graphics.FromImage(frame)) {
                g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                g.DrawImage(large,new Rectangle(0,0,40,40),0,0,160,160,GraphicsUnit.Pixel);
            }
            // x, y, width, height, source x, source y. Keep every XML slice exact.
            int[,] slices={ {2,2,3,1,0,0},{7,2,1,1,20,0},{10,2,3,1,37,0},
                {15,2,1,2,39,1},{18,2,1,1,39,20},{21,2,1,2,39,37},
                {24,2,3,1,37,39},{29,2,1,1,20,39},{32,2,3,1,0,39},
                {37,2,1,2,0,1},{40,2,1,1,0,20},{43,2,1,2,0,37} };
            for(int n=0;n<slices.GetLength(0);n++)
                for(int y=0;y<slices[n,3];y++) for(int x=0;x<slices[n,2];x++)
                    atlas.SetPixel(slices[n,0]+x,slices[n,1]+y,
                        frame.GetPixel(slices[n,4]+x,slices[n,5]+y));
            {
                Color tick=Color.FromArgb(225,170,160,138);
                int[,] strips={{2,240},{246,100}};
                for(int n=0;n<2;n++) for(int i=1;i<5;i++)
                    for(int y=15;y<29;y++)
                        atlas.SetPixel(strips[n,0]+i*strips[n,1]/5-1,y,tick);
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                byte[] header=new byte[18]; header[2]=2; header[13]=2;
                header[14]=128; header[16]=32; header[17]=40; output.Write(header);
                for(int y=0;y<128;y++) for(int x=0;x<512;x++) {
                    Color c=atlas.GetPixel(x,y);
                    output.Write(c.B); output.Write(c.G); output.Write(c.R); output.Write(c.A);
                }
            }
        }
    }
}
