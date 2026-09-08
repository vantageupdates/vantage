// Code-native skin primitives, adapted from the existing SoftGoldRenderer.
// Generates only the dedicated control-edge atlas; never processes item art.
using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class VantageControlEdgesRenderer {
    // Native attack drawing owns visibility/red tint. Outline the full client
    // area, not the name row; retain a transparent interior and a subpixel rim.
    public static void RenderAttack(string destination) {
        if(Path.GetFileName(destination)!="AttackIndicator.tga")
            throw new ArgumentException("Only the attack indicator atlas is supported.");
        using(var atlas=new Bitmap(512,128,PixelFormat.Format32bppArgb)) {
            using(var g=Graphics.FromImage(atlas))
            using(var path=Round(0.7f,0.7f,259.6f,54.6f,5.5f))
            using(var pen=new Pen(Color.FromArgb(210,255,255,255),0.75f)) {
                g.SmoothingMode=SmoothingMode.AntiAlias;
                g.DrawPath(pen,path);
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                byte[] header=new byte[18]; header[2]=2;
                header[13]=2; header[14]=128; header[16]=32; header[17]=40;
                output.Write(header);
                for(int y=0;y<128;y++) for(int x=0;x<512;x++) {
                    Color c=atlas.GetPixel(x,y);
                    output.Write(c.B); output.Write(c.G); output.Write(c.R); output.Write(c.A);
                }
            }
        }
    }
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
                int[,] strips={{2,240},{246,100}};
                // Neutral transparent relief, clipped by a live HP gauge.
                // No static marks remain visible when a party slot is empty.
                for(int n=0;n<2;n++) {
                    int start=strips[n,0], width=strips[n,1];
                    for(int y=3;y<18;y++) for(int x=1;x<width-1;x++) {
                        float edge=Math.Min(x,width-1-x);
                        float curve=Math.Max(0,7-edge);
                        float dy=y-10;
                        if(curve*curve+dy*dy>49 && edge<7) continue;
                        int alpha=y<=9 ? (int)Math.Round(50.0*(10-y)/7) : (int)Math.Round(38.0*(y-10)/7);
                        int rgb=y<=9 ? 255 : 0;
                        bool divider=false;
                        for(int i=1;i<5;i++) if(x==i*width/5-1) divider=true;
                        // Slight visibility lift only: 14% white, still translucent.
                        if(divider) { alpha=36; rgb=255; }
                        atlas.SetPixel(start+x,12+y,Color.FromArgb(alpha,rgb,rgb,rgb));
                    }
                }
            }
            // Spell-only neutral outline. A static screen piece draws this
            // after the native school-tinted gem; never tint the grey border.
            // Dedicated 120x28 cell, clear of HP strips and shared gold slices.
            using(var high=new Bitmap(480,112,PixelFormat.Format32bppArgb))
            using(var edge=new Bitmap(120,28,PixelFormat.Format32bppArgb)) {
                using(var g=Graphics.FromImage(high))
                using(var path=Round(3,3,474,106,22))
                using(var pen=new Pen(Color.FromArgb(155,148,148,148),4)) {
                    g.SmoothingMode=SmoothingMode.AntiAlias;
                    g.DrawPath(pen,path);
                }
                using(var g=Graphics.FromImage(edge)) {
                    g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    g.DrawImage(high,new Rectangle(0,0,120,28),0,0,480,112,GraphicsUnit.Pixel);
                }
                for(int y=0;y<28;y++) for(int x=0;x<120;x++)
                    atlas.SetPixel(2+x,34+y,edge.GetPixel(x,y));
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
